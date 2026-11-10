from django.db.models import Count, Avg
from django.utils import timezone
from django.db import transaction
from django.db.models import F, Sum
from django.utils.dateparse import parse_datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
import json, os, re, urllib.request, urllib.error, base64, logging
from django.conf import settings
from rest_framework import generics, status, viewsets
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from .models import User, Course, Enrollment, Assessment, Attempt, QuestionSubmission, QuestionPracticeRecord, Payment, PayPalWebhookEvent, Refund, Payout, PayPalDispute, WithdrawnEnrollment
from .serializers import UserSerializer, RegisterSerializer, CourseSerializer, EnrollmentSerializer, AssessmentSerializer, AttemptSerializer, QuestionSubmissionSerializer
from .permissions import IsApproved, IsAdminRole, IsTrainerOrAdmin

logger = logging.getLogger(__name__)

class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all(); serializer_class = RegisterSerializer; permission_classes = [AllowAny]
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data); serializer.is_valid(raise_exception=True); user=serializer.save()
        message = ('Your learner account is ready; you can sign in now.' if user.role == 'trainee' else 'Your trainer request has been submitted. An administrator must approve your account before you can teach.')
        return Response({'message':f'Welcome to CAPACITY CONNECT. {message}','username':user.username,'role':user.role,'is_approved':user.is_approved}, status=status.HTTP_201_CREATED)

@api_view(['GET','PATCH'])
@permission_classes([IsAuthenticated, IsApproved])
def me(request):
    if request.method == 'GET': return Response(UserSerializer(request.user, context={'request': request}).data)
    allowed = {'first_name','last_name','email','department','bio','competencies'}
    if request.user.role == 'trainer' or request.user.is_superuser: allowed.add('paypal_email')
    payload = {key: value for key, value in request.data.items() if key in allowed}
    serializer = UserSerializer(
        request.user, data=payload, partial=True,
        context={'request': request},
    )
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsApproved])
def become_trainer(request):
    if request.user.is_superuser or request.user.role == 'admin':
        return Response({'detail':'Administrator accounts cannot switch to trainer mode.'},status=400)
    request.user.role='trainer'
    request.user.is_approved=False
    request.user.save(update_fields=['role','is_approved'])
    return Response({'message':'Your trainer request has been submitted. An administrator must approve your account before you can teach.','user':UserSerializer(request.user).data}, status=202)

class CourseViewSet(viewsets.ModelViewSet):
    serializer_class = CourseSerializer
    permission_classes = [IsAuthenticated, IsApproved]
    def get_queryset(self):
        qs=Course.objects.select_related('trainer').annotate(enrollment_count=Count('enrollments')).order_by('-created_at')
        user=self.request.user
        if user.role == 'trainer' and self.action in ['update','partial_update','destroy']:
            return qs.filter(trainer=user)
        if user.role == 'trainee': return qs.filter(is_published=True)
        return qs
    def get_permissions(self):
        if self.action in ['create']: return [IsAuthenticated(), IsApproved(), IsTrainerOrAdmin()]
        return super().get_permissions()
    def perform_create(self, serializer):
        trainer = None if self.request.user.role == 'admin' or self.request.user.is_superuser else self.request.user
        serializer.save(trainer=trainer)
    def update(self, request, *args, **kwargs):
        obj=self.get_object()
        if request.user.role != 'admin' and not request.user.is_superuser and obj.trainer_id != request.user.id: return Response({'detail':'You can only edit your own courses.'},status=403)
        return super().update(request,*args,**kwargs)
    def destroy(self, request, *args, **kwargs):
        obj=self.get_object()
        if request.user.role != 'admin' and not request.user.is_superuser and obj.trainer_id != request.user.id: return Response({'detail':'You can only delete your own courses.'},status=403)
        return super().destroy(request,*args,**kwargs)
    @action(detail=True, methods=['post'])
    def enroll(self, request, pk=None):
        if request.user.role == 'admin' or request.user.is_superuser: return Response({'detail':'Admin accounts do not need to enroll in courses.'},status=403)
        course=self.get_object()
        if course.price > 0:
            return Response({'detail':'This is a paid course. Complete checkout before enrolling.'}, status=402)
        enrollment, created=Enrollment.objects.get_or_create(trainee=request.user,course=course)
        return Response({'message':'Enrolled successfully.' if created else 'You are already enrolled.','enrollment_id':enrollment.id},status=201 if created else 200)


def _paypal_request(path, method='GET', payload=None, request_id=None):
    client_id = getattr(settings, 'PAYPAL_CLIENT_ID', '')
    secret = getattr(settings, 'PAYPAL_CLIENT_SECRET', '')
    if not client_id or not secret:
        raise ValueError('PayPal is not configured. Add sandbox credentials to backend .env.')
    token_url = settings.PAYPAL_BASE_URL.rstrip('/') + '/v1/oauth2/token'
    auth = base64.b64encode(f'{client_id}:{secret}'.encode()).decode()
    req = urllib.request.Request(token_url, data=b'grant_type=client_credentials', headers={'Authorization':f'Basic {auth}','Content-Type':'application/x-www-form-urlencoded'}, method='POST')
    with urllib.request.urlopen(req, timeout=20) as response:
        token = json.loads(response.read())['access_token']
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {'Authorization':f'Bearer {token}','Content-Type':'application/json'}
    if request_id: headers['PayPal-Request-Id'] = request_id
    req = urllib.request.Request(settings.PAYPAL_BASE_URL.rstrip('/') + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read())


def _paypal_verify_webhook_signature(headers, webhook_id, raw_event_body):
    """Verify using the exact raw event JSON bytes PayPal delivered."""
    client_id = getattr(settings, 'PAYPAL_CLIENT_ID', '')
    secret = getattr(settings, 'PAYPAL_CLIENT_SECRET', '')
    if not client_id or not secret:
        raise ValueError('PayPal is not configured. Add sandbox credentials to backend .env.')
    token_url = settings.PAYPAL_BASE_URL.rstrip('/') + '/v1/oauth2/token'
    auth = base64.b64encode(f'{client_id}:{secret}'.encode()).decode()
    token_req = urllib.request.Request(
        token_url, data=b'grant_type=client_credentials',
        headers={'Authorization': f'Basic {auth}', 'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST',
    )
    with urllib.request.urlopen(token_req, timeout=20) as response:
        token = json.loads(response.read())['access_token']
    metadata = {
        'auth_algo': headers['auth_algo'], 'cert_url': headers['cert_url'],
        'transmission_id': headers['transmission_id'], 'transmission_sig': headers['transmission_sig'],
        'transmission_time': headers['transmission_time'], 'webhook_id': webhook_id,
    }
    # Keep PayPal's webhook_event bytes intact; re-serializing parsed JSON can invalidate verification.
    request_body = json.dumps(metadata, separators=(',', ':')).encode()[:-1] + b',"webhook_event":' + raw_event_body + b'}'
    verify_req = urllib.request.Request(
        settings.PAYPAL_BASE_URL.rstrip('/') + '/v1/notifications/verify-webhook-signature',
        data=request_body,
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(verify_req, timeout=30) as response:
        return json.loads(response.read())




def _course_repayment_source(learner, course):
    """Return the latest purchase whose refund created the current access debt.

    Refund repayment is scoped to one purchase. Older, fully-refunded purchases
    remain in the ledger but must not be added to a later purchase's repayment.
    """
    return Payment.objects.filter(
        learner=learner,
        course=course,
        payment_type='purchase',
        status__in=('captured', 'refunded'),
    ).order_by('-captured_at', '-created_at', '-pk').first()


def _course_repayment_due(learner, course, source_payment=None):
    """Outstanding refund amount for the latest affected purchase only."""
    source = source_payment or _course_repayment_source(learner, course)
    if not source:
        return Decimal('0.00')
    repayment_credits = Payment.objects.filter(
        learner=learner,
        course=course,
        payment_type='reinstatement',
        source_payment=source,
        status__in=('captured', 'refunded'),
    ).aggregate(
        total=Sum('gross_amount') - Sum('refunded_amount')
    )['total'] or Decimal('0.00')
    outstanding = Decimal(str(source.refunded_amount)) - Decimal(str(repayment_credits))
    return max(outstanding, Decimal('0.00')).quantize(Decimal('0.01'))

def _platform_fee_percent():
    """Fee percentage as a Decimal in [0, 100]; falls back to 1 if the setting is invalid so a capture never crashes after PayPal has charged the buyer."""
    try:
        value = Decimal(str(getattr(settings, 'PLATFORM_FEE_PERCENT', '1')).strip())
        if value < 0 or value > 100: raise InvalidOperation
        return value
    except (InvalidOperation, ValueError):
        return Decimal('1')


@transaction.atomic
@api_view(['POST'])
@permission_classes([IsAuthenticated, IsApproved])
def paypal_create_order(request):
    try:
        course = Course.objects.select_for_update().get(pk=request.data.get('course_id'), is_published=True)
    except (Course.DoesNotExist, TypeError, ValueError):
        return Response({'detail':'Course not found.'}, status=404)
    if Enrollment.objects.filter(trainee=request.user, course=course).exists():
        return Response({'detail':'You are already enrolled.'}, status=409)

    purpose = str(request.data.get('purpose', 'purchase')).strip().lower()
    if purpose not in ('purchase', 'reinstatement'):
        return Response({'detail': 'Invalid payment purpose.'}, status=400)
    if purpose == 'purchase' and course.price <= 0:
        return Response({'detail':'This course is free; use the enroll action.'}, status=400)

    repayment_source = _course_repayment_source(request.user, course)
    repayment_due = _course_repayment_due(request.user, course, repayment_source)
    has_prior_capture = Payment.objects.filter(
        learner=request.user, course=course, status__in=('captured', 'refunded')
    ).exists()

    if purpose == 'reinstatement':
        if repayment_due <= Decimal('0.00'):
            return Response({'detail': 'No refund repayment is due. Use Restore access instead.'}, status=409)
        checkout_amount = repayment_due
    else:
        if repayment_due > Decimal('0.00'):
            return Response({
                'detail': f'Pay the outstanding refunded amount ({course.currency} {repayment_due:.2f}) to restore access.',
                'repayment_due': str(repayment_due),
                'requires_reinstatement': True,
            }, status=409)
        if has_prior_capture:
            return Response({
                'detail': 'You have already paid for this course. Restore your access instead of purchasing it again.',
                'previously_paid': True,
                'rejoin_url': f'/courses/{course.id}/rejoin/',
            }, status=409)
        checkout_amount = course.price

    # Reuse an open checkout only for the same purpose and quoted amount.
    pending = Payment.objects.filter(
        learner=request.user, course=course, status='created', payment_type=purpose
    ).order_by('-created_at').first()
    # Only reuse an open checkout if the course price is still what the learner was quoted.
    if pending and pending.gross_amount == checkout_amount and pending.currency == course.currency:
        try:
            existing_order = _paypal_request(f'/v2/checkout/orders/{pending.paypal_order_id}')
            approve = next((
                link.get('href') for link in existing_order.get('links', [])
                if link.get('rel') in ('approve', 'payer-action')
            ), None)
            existing_status = existing_order.get('status')
            if existing_status in ('CREATED', 'PAYER_ACTION_REQUIRED') and approve:
                return Response({
                    'order_id': pending.paypal_order_id,
                    'status': existing_status,
                    'approve_url': approve,
                    'reused': True,
                }, status=200)
            if existing_status in ('APPROVED', 'COMPLETED'):
                return Response({
                    'order_id': pending.paypal_order_id,
                    'status': existing_status,
                    'return_url': settings.FRONTEND_URL.rstrip('/') + '/?token=' + pending.paypal_order_id,
                    'reused': True,
                }, status=200)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, KeyError):
            # Fall through and create a fresh order if the old one is no longer usable.
            pass
    try:
        amount = f'{checkout_amount:.2f}'
        order = _paypal_request('/v2/checkout/orders', 'POST', {
            'intent':'CAPTURE',
            'purchase_units':[{'reference_id':str(course.id),'custom_id':f'{request.user.id}:{course.id}',
                'description':course.title[:127],
                'amount':{'currency_code':course.currency,'value':amount}}],
            'payment_source':{'paypal':{'experience_context':{'user_action':'PAY_NOW','return_url':settings.FRONTEND_URL.rstrip('/') + '/?payment=success','cancel_url':settings.FRONTEND_URL.rstrip('/') + '/?payment=cancel'}}}
        }, request_id=f'cc-{purpose}-{request.user.id}-{course.id}-{int(timezone.now().timestamp())}')
        # Persist the checkout before returning the buyer to PayPal. Capture relies
        # on this learner-owned record to bind the PayPal order to the course/price.
        order_id = order.get('id')
        if not order_id:
            raise ValueError('PayPal did not return an order ID.')
        Payment.objects.update_or_create(
            paypal_order_id=order_id,
            defaults={
                'learner': request.user,
                'course': course,
                'gross_amount': checkout_amount,
                'platform_fee': Decimal('0.00'),
                'trainer_share': Decimal('0.00'),
                'currency': course.currency,
                'payment_type': purpose,
                'source_payment': repayment_source if purpose == 'reinstatement' else None,
                'status': 'created',
            },
        )
        # PayPal's approval relation can be named `approve` or `payer-action`
        # depending on the checkout integration/version.
        approve = next((
            link.get('href') for link in order.get('links', [])
            if link.get('rel') in ('approve', 'payer-action')
        ), None)
        if not approve:
            return Response({'detail':'PayPal created the order but did not return an approval URL.','order_id':order_id}, status=502)
        return Response({'order_id':order_id,'status':order.get('status'),'approve_url':approve}, status=201)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, KeyError) as exc:
        detail = exc.read().decode(errors='replace') if isinstance(exc, urllib.error.HTTPError) else str(exc)
        return Response({'detail':f'PayPal order creation failed: {detail[:500]}'}, status=502)


@transaction.atomic
@api_view(['POST'])
@permission_classes([IsAuthenticated, IsApproved])
def paypal_capture_order(request):
    order_id = str(request.data.get('order_id', '')).strip()
    if not order_id:
        return Response({'detail': 'order_id is required.'}, status=400)

    existing = Payment.objects.filter(paypal_order_id=order_id, status='captured').first()
    if existing:
        if existing.learner_id != request.user.id:
            return Response({'detail': 'Order does not belong to this account.'}, status=403)
        enrollment, _ = Enrollment.objects.get_or_create(
            trainee=request.user, course=existing.course
        )
        return Response({
            'message': 'Payment already captured.',
            'enrollment_id': enrollment.id,
            'payment_id': existing.id,
        })

    pending = Payment.objects.select_for_update().filter(
        paypal_order_id=order_id, learner=request.user, status='created'
    ).select_related('course').first()
    if not pending:
        # A concurrent request may have completed the same capture while this
        # request waited for the row lock. Re-read and return the idempotent result.
        completed = Payment.objects.filter(
            paypal_order_id=order_id, learner=request.user, status='captured'
        ).select_related('course').first()
        if completed:
            enrollment, _ = Enrollment.objects.get_or_create(
                trainee=request.user, course=completed.course
            )
            return Response({
                'message': 'Payment already captured.',
                'enrollment_id': enrollment.id,
                'payment_id': completed.id,
            })
        return Response({'detail': 'No pending checkout found for this account and order.'}, status=404)

    try:
        # Read the canonical order first. In PayPal's capture response, custom_id
        # is not guaranteed to be repeated on the purchase unit.
        order = _paypal_request(f'/v2/checkout/orders/{order_id}')
        units = order.get('purchase_units') or []
        if len(units) != 1:
            return Response({'detail': 'PayPal order must contain exactly one purchase unit.'}, status=400)

        unit = units[0]
        expected_custom_id = f'{request.user.id}:{pending.course_id}'
        if unit.get('custom_id') != expected_custom_id:
            return Response({'detail': 'Order metadata does not match this checkout.'}, status=400)

        order_amount = unit.get('amount') or {}
        if (order_amount.get('currency_code') != pending.currency or
                Decimal(str(order_amount.get('value', '0'))) != pending.gross_amount):
            return Response({'detail': 'PayPal order amount does not match the checkout amount.'}, status=400)

        # A previous request may already have captured the order even if the
        # browser received an error. Reconcile that completed capture instead
        # of attempting to charge the buyer again.
        if pending.payment_type == 'purchase' and (
                pending.gross_amount != pending.course.price or pending.currency != pending.course.currency):
            return Response({
                'detail': 'The course price changed after this checkout was created. Nothing was charged. Please start the purchase again.',
                'price_changed': True,
            }, status=409)
        if pending.payment_type == 'reinstatement':
            current_source = _course_repayment_source(request.user, pending.course)
            current_due = _course_repayment_due(request.user, pending.course, current_source)
            if current_source is None or pending.source_payment_id != current_source.id or current_due != pending.gross_amount:
                return Response({
                    'detail': 'The repayment amount changed while checkout was open. Nothing was charged. Please start checkout again.',
                    'repayment_due': str(current_due),
                }, status=409)

        if order.get('status') == 'COMPLETED':
            captures = (unit.get('payments') or {}).get('captures') or []
        elif order.get('status') == 'APPROVED':
            result = _paypal_request(
                f'/v2/checkout/orders/{order_id}/capture',
                'POST', {}, request_id=f'cc-capture-{order_id}'
            )
            if result.get('status') != 'COMPLETED':
                return Response({
                    'detail': 'PayPal has not marked this order as completed.',
                    'paypal_status': result.get('status'),
                }, status=402)
            result_units = result.get('purchase_units') or []
            captures = ((result_units[0].get('payments') or {}).get('captures') or []) if result_units else []
            # If the capture response omits capture details, refresh the order.
            if not captures:
                refreshed = _paypal_request(f'/v2/checkout/orders/{order_id}')
                refreshed_units = refreshed.get('purchase_units') or []
                captures = (((refreshed_units[0].get('payments') or {}).get('captures') or [])
                            if refreshed_units else [])
        else:
            return Response({
                'detail': 'PayPal order is not approved for capture.',
                'paypal_status': order.get('status'),
            }, status=402)

        if not captures:
            return Response({'detail': 'PayPal order is completed but no capture details were returned.'}, status=502)

        capture = captures[0]
        if capture.get('status') != 'COMPLETED':
            return Response({
                'detail': 'PayPal capture is not completed.',
                'capture_status': capture.get('status'),
            }, status=402)

        capture_amount = capture.get('amount') or {}
        paid_amount = Decimal(str(capture_amount.get('value', '0')))
        if (capture_amount.get('currency_code') != pending.currency or
                paid_amount != pending.gross_amount):
            return Response({'detail': 'Captured amount does not match the checkout amount.'}, status=400)

        capture_id = capture.get('id')
        if not capture_id:
            return Response({'detail': 'PayPal did not return a capture ID.'}, status=502)

        fee_pct = _platform_fee_percent()
        fee = (paid_amount * fee_pct / Decimal('100')).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        share = paid_amount - fee

        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(pk=pending.pk)
            if payment.status == 'captured':
                enrollment, _ = Enrollment.objects.get_or_create(
                    trainee=request.user, course=payment.course
                )
                return Response({
                    'message': 'Payment already captured.',
                    'enrollment_id': enrollment.id,
                    'payment_id': payment.id,
                })
            payment.paypal_capture_id = capture_id
            payment.platform_fee = fee
            payment.trainer_share = share
            payment.status = 'captured'
            payment.captured_at = timezone.now()
            payment.save(update_fields=[
                'paypal_capture_id', 'platform_fee', 'trainer_share',
                'status', 'captured_at'
            ])
            enrollment, _ = Enrollment.objects.get_or_create(
                trainee=request.user, course=pending.course
            )

        return Response({
            'message': 'Payment captured and course unlocked.',
            'enrollment_id': enrollment.id,
            'payment_id': payment.id,
        })
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, KeyError,
            Course.DoesNotExist, IndexError) as exc:
        detail = exc.read().decode(errors='replace') if isinstance(exc, urllib.error.HTTPError) else str(exc)
        return Response({'detail': f'Payment capture failed: {detail[:500]}'}, status=502)


def _payment_net_financials(payment):
    """Return proportional net fee/share after completed refunds, preserving original captured values."""
    net_amount = max(Decimal('0.00'), payment.gross_amount - payment.refunded_amount)
    if payment.gross_amount <= 0:
        return net_amount, Decimal('0.00'), Decimal('0.00')
    net_fee = (payment.platform_fee * net_amount / payment.gross_amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    net_share = net_amount - net_fee
    return net_amount, net_fee, net_share


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsApproved])
def payment_history(request):
    qs = Payment.objects.select_related('course', 'learner').prefetch_related('refunds')
    if request.user.is_superuser or request.user.role == 'admin':
        pass
    elif request.user.role == 'trainee':
        qs = qs.filter(learner=request.user)
    else:
        qs = qs.filter(course__trainer_id=request.user.pk)
    return Response([{
        'id': p.id,
        'course_id': p.course_id,
        'course_title': p.course.title,
        'learner_id': p.learner_id,
        'learner_name': p.learner.get_full_name() or p.learner.username,
        'gross_amount': str(p.gross_amount),
        'platform_fee': str(p.platform_fee),
        'trainer_share': str(p.trainer_share),
        'net_amount': str(_payment_net_financials(p)[0]),
        'net_platform_fee': str(_payment_net_financials(p)[1]),
        'net_trainer_share': str(_payment_net_financials(p)[2]),
        'currency': p.currency,
        'status': p.status,
        'refunded_amount': str(p.refunded_amount),
        'refunds': [{'refund_id': r.paypal_refund_id, 'amount': str(r.amount), 'currency': r.currency, 'status': r.status, 'created_at': r.created_at} for r in p.refunds.all()],
        'created_at': p.created_at,
        'captured_at': p.captured_at,
    } for p in qs])


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsApproved])
def transactions_and_enrollments(request):
    """
    Role-aware learning and transaction ledger.
    - Learners: their purchases (including historical/withdrawn purchases) and free enrollments.
    - Trainers: active enrollments in their own courses, with payment status only.
    - Admins: every payment plus free/unpaid active enrollments.
    """
    user = request.user
    is_admin = user.is_superuser or user.role == 'admin'
    is_trainer = user.role == 'trainer' and not is_admin

    if is_trainer:
        enrollments = Enrollment.objects.filter(
            course__trainer_id=user.pk
        ).select_related('trainee', 'course', 'course__trainer').order_by('-enrolled_at')
        enrollment_by_key = {
            (enrollment.trainee_id, enrollment.course_id): enrollment
            for enrollment in enrollments
        }
        payments = Payment.objects.filter(
            course__trainer_id=user.pk
        ).select_related('learner', 'course', 'course__trainer').prefetch_related('refunds').order_by('-created_at')
        rows = []
        payment_keys = set()
        for payment in payments:
            key = (payment.learner_id, payment.course_id)
            payment_keys.add(key)
            enrollment = enrollment_by_key.get(key)
            net_amount, net_fee, net_share = _payment_net_financials(payment)
            rows.append({
                'id': f'payment-{payment.id}',
                'record_type': 'purchase',
                'enrollment_id': enrollment.id if enrollment else None,
                'payment_id': payment.id,
                'invoice_number': f'CC-INV-{payment.id:06d}' if payment.status in ('captured', 'refunded') else None,
                'course_id': payment.course_id,
                'course_title': payment.course.title,
                'learner_id': payment.learner_id,
                'learner_name': payment.learner.get_full_name() or payment.learner.username,
                'learner_email': payment.learner.email,
                'trainer_id': user.id,
                'trainer_name': user.get_full_name() or user.username,
                'amount': str(payment.gross_amount),
                'gross_amount': str(payment.gross_amount),
                'refunded_amount': str(payment.refunded_amount),
                'net_amount': str(net_amount),
                'platform_fee': str(net_fee),
                'trainer_share': str(net_share),
                'currency': payment.currency,
                'payment_status': payment.status,
                'purchased_at': payment.captured_at,
                'enrolled_at': enrollment.enrolled_at if enrollment else None,
                'enrollment_active': enrollment is not None,
                'progress': enrollment.progress if enrollment else None,
                'completed': enrollment.completed if enrollment else None,
            })

        # Preserve visibility of free/unpaid enrollments that have no payment row.
        for enrollment in enrollments:
            key = (enrollment.trainee_id, enrollment.course_id)
            if key in payment_keys:
                continue
            rows.append({
                'id': f'enrollment-{enrollment.id}',
                'record_type': 'enrollment',
                'enrollment_id': enrollment.id,
                'payment_id': None,
                'invoice_number': None,
                'course_id': enrollment.course_id,
                'course_title': enrollment.course.title,
                'learner_id': enrollment.trainee_id,
                'learner_name': enrollment.trainee.get_full_name() or enrollment.trainee.username,
                'learner_email': enrollment.trainee.email,
                'trainer_id': user.id,
                'trainer_name': user.get_full_name() or user.username,
                'amount': '0.00' if enrollment.course.price <= 0 else None,
                'gross_amount': '0.00' if enrollment.course.price <= 0 else None,
                'refunded_amount': '0.00',
                'net_amount': '0.00' if enrollment.course.price <= 0 else None,
                'platform_fee': '0.00' if enrollment.course.price <= 0 else None,
                'trainer_share': '0.00' if enrollment.course.price <= 0 else None,
                'currency': enrollment.course.currency,
                'payment_status': 'free' if enrollment.course.price <= 0 else 'unrecorded',
                'purchased_at': None,
                'enrolled_at': enrollment.enrolled_at,
                'enrollment_active': True,
                'progress': enrollment.progress,
                'completed': enrollment.completed,
            })
    else:
        if is_admin:
            payments = Payment.objects.select_related(
                'learner', 'course', 'course__trainer'
            ).all().order_by('-created_at')
            enrollments = Enrollment.objects.select_related(
                'trainee', 'course', 'course__trainer'
            ).all().order_by('-enrolled_at')
        else:
            payments = Payment.objects.filter(
                learner=user
            ).select_related('learner', 'course', 'course__trainer').prefetch_related('refunds').order_by('-created_at')
            enrollments = Enrollment.objects.filter(
                trainee=user
            ).select_related('trainee', 'course', 'course__trainer').order_by('-enrolled_at')

        rows = []
        captured_keys = set()
        active_keys = set()
        for enrollment in enrollments:
            active_keys.add((enrollment.trainee_id, enrollment.course_id))

        for payment in payments:
            key = (payment.learner_id, payment.course_id)
            active = key in active_keys
            if payment.status == 'captured':
                captured_keys.add(key)
            trainer = payment.course.trainer
            rows.append({
                'id': f'payment-{payment.id}',
                'record_type': 'purchase',
                'enrollment_id': None,
                'payment_id': payment.id,
                'invoice_number': f'CC-INV-{payment.id:06d}' if payment.status == 'captured' else None,
                'paypal_order_id': payment.paypal_order_id,
                'paypal_capture_id': payment.paypal_capture_id,
                'course_id': payment.course_id,
                'course_title': payment.course.title,
                'learner_id': payment.learner_id,
                'learner_name': payment.learner.get_full_name() or payment.learner.username,
                'learner_email': payment.learner.email,
                'trainer_id': trainer.id if trainer else None,
                'trainer_name': (trainer.get_full_name() or trainer.username) if trainer else 'Unassigned',
                'amount': str(payment.gross_amount),
                'platform_fee': str(_payment_net_financials(payment)[1]),
                'trainer_share': str(_payment_net_financials(payment)[2]),
                'currency': payment.currency,
                'payment_status': payment.status,
                'refunded_amount': str(payment.refunded_amount),
                'refunds': [{'refund_id': r.paypal_refund_id, 'amount': str(r.amount), 'currency': r.currency, 'status': r.status, 'created_at': r.created_at} for r in payment.refunds.all()],
                'purchased_at': payment.captured_at,
                'enrolled_at': None,
                'enrollment_active': active,
                'progress': None,
                'completed': None,
                'created_at': payment.created_at,
            })

        # Free enrollments (and any enrollment without a captured purchase) are
        # represented separately so the ledger never labels them as a payment.
        for enrollment in enrollments:
            key = (enrollment.trainee_id, enrollment.course_id)
            if key in captured_keys:
                # Attach the active enrollment state to the matching captured purchase.
                for row in rows:
                    if row['record_type'] == 'purchase' and row['learner_id'] == enrollment.trainee_id and row['course_id'] == enrollment.course_id and row['payment_status'] == 'captured':
                        row['enrollment_id'] = enrollment.id
                        row['enrolled_at'] = enrollment.enrolled_at
                        row['progress'] = enrollment.progress
                        row['completed'] = enrollment.completed
                        row['enrollment_active'] = True
                continue
            trainer = enrollment.course.trainer
            rows.append({
                'id': f'enrollment-{enrollment.id}',
                'record_type': 'enrollment',
                'enrollment_id': enrollment.id,
                'payment_id': None,
                'invoice_number': None,
                'course_id': enrollment.course_id,
                'course_title': enrollment.course.title,
                'learner_id': enrollment.trainee_id,
                'learner_name': enrollment.trainee.get_full_name() or enrollment.trainee.username,
                'trainer_id': trainer.id if trainer else None,
                'trainer_name': (trainer.get_full_name() or trainer.username) if trainer else 'Unassigned',
                'amount': '0.00' if enrollment.course.price <= 0 else None,
                'platform_fee': '0.00' if enrollment.course.price <= 0 else None,
                'trainer_share': '0.00' if enrollment.course.price <= 0 else None,
                'currency': enrollment.course.currency,
                'payment_status': 'free' if enrollment.course.price <= 0 else 'unrecorded',
                'purchased_at': None,
                'enrolled_at': enrollment.enrolled_at,
                'enrollment_active': True,
                'progress': enrollment.progress,
                'completed': enrollment.completed,
                'created_at': enrollment.enrolled_at,
            })

    # Consistent newest-first response. The UI applies interactive filters and sorting.
    rows.sort(key=lambda row: str(row.get('purchased_at') or row.get('created_at') or row.get('enrolled_at') or ''), reverse=True)
    captured_rows = [row for row in rows if row['record_type'] == 'purchase' and row['payment_status'] == 'captured']
    summary = {
        'records': len(rows),
        'active_enrollments': enrollments.count(),
        'successful_purchases': len(captured_rows),
        'gross_revenue': str(sum((Decimal(row['amount']) for row in captured_rows), Decimal('0.00'))) if (is_admin or is_trainer) else None,
        'platform_fees': str(sum((Decimal(row['platform_fee']) for row in captured_rows), Decimal('0.00'))) if is_admin else None,
        'trainer_shares': str(sum((Decimal(row['trainer_share']) for row in captured_rows), Decimal('0.00'))) if (is_admin or is_trainer) else None,
    }
    return Response({'items': rows, 'summary': summary})


class MyEnrollmentsView(generics.ListAPIView):
    serializer_class=EnrollmentSerializer; permission_classes=[IsAuthenticated,IsApproved]
    def get_queryset(self): return Enrollment.objects.filter(trainee=self.request.user).select_related('course','course__trainer')


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsApproved])
def withdraw_from_course(request, course_id):
    if request.user.role != 'trainee':
        return Response({'detail': 'Only learners can withdraw from courses.'}, status=403)
    enrollment = Enrollment.objects.filter(trainee=request.user, course_id=course_id).select_related('course').first()
    if not enrollment:
        return Response({'detail': 'You are not enrolled in this course.'}, status=404)
    course_title = enrollment.course.title
    # Deliberately remove access only. Captured Payment records are retained and
    # no refund or reversal is initiated by this action.
    WithdrawnEnrollment.objects.update_or_create(
        trainee=request.user, course=enrollment.course,
        defaults={'progress': enrollment.progress, 'completed': enrollment.completed},
    )
    enrollment.delete()
    return Response({
        'message': f'You have withdrawn from "{course_title}". Course access has been removed. No refund has been issued.',
        'refund_issued': False,
    }, status=200)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsApproved])
def rejoin_paid_course(request, course_id):
    if request.user.role != 'trainee':
        return Response({'detail': 'Only learners can rejoin courses.'}, status=403)
    course = Course.objects.filter(pk=course_id, is_published=True).first()
    if not course:
        return Response({'detail': 'Course not found.'}, status=404)
    repayment_due = _course_repayment_due(request.user, course)
    if repayment_due > Decimal('0.00'):
        return Response({
            'detail': 'Repay the refunded amount before restoring course access.',
            'repayment_due': str(repayment_due),
            'currency': course.currency,
        }, status=402)
    paid_before = Payment.objects.filter(
        learner=request.user, course=course, status__in=('captured', 'refunded')
    ).exists()
    if not paid_before:
        return Response({'detail': 'No completed payment was found for this course. Complete checkout first.'}, status=402)
    enrollment, created = Enrollment.objects.get_or_create(trainee=request.user, course=course)
    if created:
        saved = WithdrawnEnrollment.objects.filter(trainee=request.user, course=course).first()
        if saved:
            enrollment.progress, enrollment.completed = saved.progress, saved.completed
            enrollment.save(update_fields=['progress', 'completed'])
            saved.delete()
    return Response({
        'message': 'Your previous purchase was found. Course access has been restored without another charge.' if created else 'You are already enrolled.',
        'enrollment_id': enrollment.id,
        'created': created,
    }, status=201 if created else 200)

def sync_assessment_questions_to_bank(assessment):
    """Ensure every saved assessment question has a canonical Question Bank entry.

    Assessment questions remain embedded JSON for backwards compatibility, but each
    one receives question_bank_id pointing at the corresponding approved bank item.
    """
    questions = assessment.questions or []
    if not isinstance(questions, list) or not questions:
        return
    author = assessment.created_by
    if not author or author.role not in ['trainer', 'admin']:
        author = assessment.course.trainer
    if not author:
        return
    changed = False
    for item in questions:
        if not isinstance(item, dict) or not item.get('text'):
            continue
        linked_id = item.get('question_bank_id')
        bank_item = None
        if linked_id:
            bank_item = QuestionSubmission.objects.filter(pk=linked_id, course=assessment.course).first()
        normalized = ' '.join(str(item['text']).lower().split())
        if bank_item is None:
            candidates = QuestionSubmission.objects.filter(course=assessment.course).exclude(status='rejected')
            for candidate in candidates:
                if ' '.join(candidate.question_text.lower().split()) == normalized:
                    bank_item = candidate
                    break
        options = item.get('options') or []
        try:
            correct_answer = int(item.get('correct_answer', 0))
        except (TypeError, ValueError):
            correct_answer = 0
        if bank_item is None:
            bank_item = QuestionSubmission.objects.create(
                submitted_by=author, course=assessment.course,
                question_text=str(item['text']), options=options,
                correct_answer=max(0, min(correct_answer, max(len(options) - 1, 0))),
                explanation=str(item.get('explanation', '')),
                topic=assessment.course.category or 'General', difficulty='beginner',
                status='approved', reviewed_by=author, reviewed_at=timezone.now(),
                published_at=timezone.now(),
            )
        else:
            # Keep the Question Bank's content aligned with the assessment's actual
            # options and answer; assessment questions are already publishable content.
            bank_item.question_text = str(item['text'])
            bank_item.options = options
            bank_item.correct_answer = max(0, min(correct_answer, max(len(options) - 1, 0)))
            bank_item.explanation = str(item.get('explanation', bank_item.explanation or ''))
            bank_item.status = 'approved'
            bank_item.reviewed_by = author
            bank_item.reviewed_at = bank_item.reviewed_at or timezone.now()
            bank_item.published_at = bank_item.published_at or timezone.now()
            bank_item.save()
        if str(item.get('question_bank_id', '')) != str(bank_item.id):
            item['question_bank_id'] = bank_item.id
            changed = True
    if changed:
        assessment.questions = questions
        assessment.save(update_fields=['questions'])


class AssessmentViewSet(viewsets.ModelViewSet):
    serializer_class=AssessmentSerializer; permission_classes=[IsAuthenticated,IsApproved]
    def get_queryset(self):
        qs=Assessment.objects.select_related('course','created_by').order_by('-created_at')
        user=self.request.user
        if user.role == 'trainee': return qs.filter(is_published=True,course__enrollments__trainee=user).distinct()
        if user.role == 'trainer':
            from django.db.models import Q
            return qs.filter(Q(course__trainer=user) | Q(is_published=True,course__enrollments__trainee=user)).distinct()
        return qs
    def get_permissions(self):
        if self.action in ['create','update','partial_update','destroy']: return [IsAuthenticated(),IsApproved(),IsTrainerOrAdmin()]
        return super().get_permissions()
    def perform_create(self, serializer):
        course=serializer.validated_data['course']; user=self.request.user
        if user.role=='trainer' and course.trainer_id != user.id: raise PermissionError('Trainers can only create assessments for their own courses.')
        assessment = serializer.save(created_by=user)
        sync_assessment_questions_to_bank(assessment)
    def perform_update(self, serializer):
        assessment = serializer.save()
        sync_assessment_questions_to_bank(assessment)
    def create(self, request, *args, **kwargs):
        try: return super().create(request,*args,**kwargs)
        except PermissionError as e: return Response({'detail':str(e)},status=403)
    def update(self, request, *args, **kwargs):
        obj=self.get_object()
        if request.user.role=='trainer' and obj.course.trainer_id != request.user.id: return Response({'detail':'You cannot edit this assessment.'},status=403)
        return super().update(request,*args,**kwargs)
    def destroy(self, request, *args, **kwargs):
        obj=self.get_object()
        if request.user.role=='trainer' and obj.course.trainer_id != request.user.id: return Response({'detail':'You cannot delete this assessment.'},status=403)
        return super().destroy(request,*args,**kwargs)
    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        assessment=self.get_object(); user=request.user
        if user.role=='admin' or user.is_superuser: return Response({'detail':'Admin accounts do not take learner assessments.'},status=403)
        if assessment.deadline and timezone.now()>assessment.deadline: return Response({'detail':'The deadline for this assessment has passed.'},status=400)
        if Attempt.objects.filter(trainee=user,assessment=assessment).exists(): return Response({'detail':'You have already submitted this assessment.'},status=409)
        answers=request.data.get('answers')
        if not isinstance(answers,dict): return Response({'detail':'Answers must be an object mapping question IDs to option indexes.'},status=400)
        questions = assessment.questions or []
        if not questions:
            return Response({'detail':'This assessment has no questions yet.'},status=400)
        # Grade answers inside Django. Correct answers are option indexes; string
        # comparison also supports indexes submitted as strings by HTML forms.
        results=[]
        correct_answers=0
        for index, question in enumerate(questions):
            question_id=str(question.get('id', index+1))
            expected=question.get('correct_answer')
            submitted=answers.get(question_id, answers.get(str(index+1)))
            is_correct=(submitted is not None and expected is not None and str(submitted)==str(expected))
            if is_correct:
                correct_answers += 1
            results.append({'question_id':question_id,'correct':is_correct})
        total_questions=len(questions)
        score=round(correct_answers/total_questions*100,2)
        result={'total_questions':total_questions,'correct_answers':correct_answers,'score':score,'results':results}
        raw_timings=request.data.get('question_timings', {})
        if not isinstance(raw_timings, dict):
            return Response({'detail':'question_timings must map question IDs to elapsed milliseconds.'},status=400)
        # Ignore malformed, negative, or implausibly large client timing values. The server
        # calculates all points; the browser never submits a score.
        timings={}
        for key,value in raw_timings.items():
            try: elapsed=max(0,min(int(value),600000))
            except (TypeError,ValueError): continue
            timings[str(key)]=elapsed
        question_results={str(item['question_id']):bool(item['correct']) for item in result.get('results',[])}
        points=0
        for index, question in enumerate(assessment.questions):
            qid=str(question.get('id',index+1))
            if question_results.get(qid,False):
                elapsed=timings.get(qid,timings.get(str(index+1),600000))
                # 10 points for a correct answer, plus at most 5 speed bonus points.
                speed_bonus=max(0,5-min(5,elapsed//6000))
                points += 10 + speed_bonus
        attempt=Attempt.objects.create(trainee=user,assessment=assessment,answers=answers,score=result['score'],total_questions=result['total_questions'],question_timings=timings,question_results=question_results,points=points)
        enrollment=Enrollment.objects.filter(trainee=user,course=assessment.course).first()
        if enrollment:
            attempts=Attempt.objects.filter(trainee=user,assessment__course=assessment.course).count()
            total=Assessment.objects.filter(course=assessment.course,is_published=True).count()
            enrollment.progress=min(100,round(attempts/max(total,1)*100)); enrollment.save(update_fields=['progress'])
        return Response({'message':'Assessment submitted.','attempt':AttemptSerializer(attempt).data,'correct_answers':result['correct_answers'],'score_percent':result['score'],'points_earned':points},status=201)

class AttemptView(generics.ListAPIView):
    serializer_class=AttemptSerializer; permission_classes=[IsAuthenticated,IsApproved]
    def get_queryset(self):
        qs=Attempt.objects.select_related('trainee','assessment','assessment__course')
        user=self.request.user
        if user.role=='trainee': return qs.filter(trainee=user)
        if user.role=='trainer':
            from django.db.models import Q
            return qs.filter(Q(trainee=user) | Q(assessment__course__trainer=user)).distinct()
        return qs


class QuestionSubmissionViewSet(viewsets.ModelViewSet):
    serializer_class = QuestionSubmissionSerializer
    permission_classes = [IsAuthenticated, IsApproved]
    http_method_names = ['get','post','put','patch','delete','head','options']

    def get_queryset(self):
        user=self.request.user
        qs=QuestionSubmission.objects.select_related('submitted_by','reviewed_by')
        if user.is_superuser or user.role == 'admin':
            status_filter=self.request.query_params.get('status')
            return qs.filter(status=status_filter) if status_filter in ['pending','approved','rejected','revision'] else qs
        if user.role == 'trainer':
            # Trainers manage every question on their own courses, but can also practise the published
            # (approved) bank of other courses and always see questions they submitted themselves.
            from django.db.models import Q
            qs = qs.filter(Q(course__trainer=user) | Q(status='approved') | Q(submitted_by=user))
            status_filter=self.request.query_params.get('status')
            return qs.filter(status=status_filter) if status_filter in ['pending','approved','rejected','revision'] else qs
        # Students can view the published question bank and their own submissions only.
        return qs.filter(models_q_for_student(user))

    def update(self, request, *args, **kwargs):
        submission = self.get_object()
        if request.user.role not in ['trainer', 'admin'] and not request.user.is_superuser:
            if submission.submitted_by_id != request.user.id or submission.status not in ['pending', 'revision']:
                return Response({'detail':'You can edit only your own questions while they are pending or need revision.'}, status=403)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        submission = self.get_object()
        if request.user.role not in ['trainer', 'admin'] and not request.user.is_superuser:
            if submission.submitted_by_id != request.user.id or submission.status not in ['pending', 'revision']:
                return Response({'detail':'You can delete only your own questions while they are pending or need revision.'}, status=403)
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['post'], url_path='grade-practice')
    def grade_practice(self, request):
        answers = request.data.get('answers')
        if not isinstance(answers, dict) or not answers:
            return Response({'detail':'answers must be a non-empty object of question IDs to option indexes.'}, status=400)
        ids = [int(k) for k in answers if str(k).isdigit()]
        qs = QuestionSubmission.objects.filter(id__in=ids, status='approved')
        by_id = {str(q.id): q for q in qs}
        if len(by_id) != len(answers):
            return Response({'detail':'One or more questions are unavailable.'}, status=400)
        results = []
        correct = 0
        awarded = 0
        with transaction.atomic():
            for qid, submitted in answers.items():
                q = by_id[str(qid)]
                try:
                    submitted_index = int(submitted)
                except (TypeError, ValueError):
                    return Response({'detail': f'Invalid option index for question {qid}.'}, status=400)
                if submitted_index < 0 or submitted_index >= len(q.options):
                    return Response({'detail': f'Invalid option index for question {qid}.'}, status=400)
                is_correct = submitted_index == q.correct_answer
                correct += int(is_correct)
                record, _ = QuestionPracticeRecord.objects.get_or_create(
                    trainee=request.user, question=q,
                    defaults={'submitted_answer': submitted_index, 'is_correct': is_correct},
                )
                points_earned = 0
                # First correct answer earns 10 points. Repeated submissions cannot farm points.
                if is_correct and record.points_earned == 0:
                    record.points_earned = 10
                    record.first_correct_at = timezone.now()
                    points_earned = 10
                record.submitted_answer = submitted_index
                record.is_correct = record.is_correct or is_correct
                record.save()
                awarded += points_earned
                results.append({'id': q.id, 'correct': is_correct, 'correct_answer': q.correct_answer, 'options': q.options, 'explanation': q.explanation, 'points_earned': points_earned})
        return Response({'correct': correct, 'total': len(results), 'points_earned': awarded, 'results': results})

    def create(self, request, *args, **kwargs):
        user = request.user
        if user.role not in ['trainee', 'trainer', 'admin'] and not user.is_superuser:
            return Response({'detail':'Your account cannot submit questions.'}, status=403)
        serializer=self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        course = serializer.validated_data.get('course')
        lesson = serializer.validated_data.get('lesson')
        if lesson and course and lesson.course_id != course.id:
            return Response({'detail':'Selected lecture must belong to the selected course.'}, status=400)
        if lesson and not course:
            course = lesson.course
        if user.role == 'trainer' and (not course or course.trainer_id != user.id):
            return Response({'detail':'Choose one of your own courses to add a question.'}, status=403)
        normalized=' '.join(serializer.validated_data['question_text'].lower().split())
        for existing in QuestionSubmission.objects.filter(status__in=['pending','approved']).only('question_text'):
            if ' '.join(existing.question_text.lower().split()) == normalized:
                return Response({'detail':'A matching question is already pending review or published.'},status=400)
        if user.role in ['trainer', 'admin'] or user.is_superuser:
            submission=serializer.save(submitted_by=user, course=course, status='approved', reviewed_by=user,
                reviewed_at=timezone.now(), published_at=timezone.now())
            message='Question added to the approved Question Bank.'
        else:
            submission=serializer.save(submitted_by=user, course=course, status='pending')
            message='Question submitted for trainer review.'
        return Response({'message':message,'submission':self.get_serializer(submission).data},status=201)

    @action(detail=True, methods=['post'])
    def review(self, request, pk=None):
        if request.user.role not in ['trainer','admin'] and not request.user.is_superuser:
            return Response({'detail':'Only trainers and administrators can review questions.'},status=403)
        submission=self.get_object()
        if request.user.role == 'trainer' and not request.user.is_superuser and submission.course_id and submission.course.trainer_id != request.user.id:
            return Response({'detail':'You can review questions only for your own courses.'}, status=403)
        decision=request.data.get('status')
        if decision not in ['approved','rejected','revision']:
            return Response({'detail':'status must be approved, rejected, or revision.'},status=400)
        feedback=str(request.data.get('review_feedback','')).strip()[:2000]
        submission.status=decision
        submission.review_feedback=feedback
        submission.reviewed_by=request.user
        submission.reviewed_at=timezone.now()
        submission.published_at=timezone.now() if decision=='approved' else None
        submission.save(update_fields=['status','review_feedback','reviewed_by','reviewed_at','published_at'])
        return Response({'message':'Question approved and published.' if decision=='approved' else 'Review decision saved.','submission':self.get_serializer(submission).data})


def models_q_for_student(user):
    from django.db.models import Q
    return Q(status='approved') | Q(submitted_by=user)


@api_view(['GET'])
@permission_classes([IsAuthenticated,IsApproved])
def leaderboard(request):
    # Only learners compete; trainers/admins must never appear in learner rankings.
    attempts=Attempt.objects.select_related('trainee','assessment','assessment__course').filter(score__gte=0, trainee__role='trainee')
    totals={}
    for attempt in attempts:
        row=totals.setdefault(attempt.trainee_id,{'user_id':attempt.trainee_id,'username':attempt.trainee.get_full_name() or attempt.trainee.username,'points':0,'correct_answers':0,'attempts':0})
        row['points']+=attempt.points
        row['correct_answers']+=sum(1 for correct in (attempt.question_results or {}).values() if correct)
        row['attempts']+=1
    # Include Question Bank practice in the same global leaderboard.
    practice_records = QuestionPracticeRecord.objects.select_related('trainee', 'question', 'question__course').filter(trainee__role='trainee')
    practice_by_question = {}
    for record in practice_records:
        row = totals.setdefault(record.trainee_id, {'user_id': record.trainee_id, 'username': record.trainee.get_full_name() or record.trainee.username, 'points': 0, 'correct_answers': 0, 'attempts': 0})
        row['points'] += record.points_earned
        if record.is_correct:
            row['correct_answers'] += 1
        practice_by_question.setdefault(record.question_id, []).append(record)

    # Reward useful community contributions: each approved question adds five points.
    approved_counts={}
    for submission in QuestionSubmission.objects.filter(status='approved', submitted_by__role='trainee').select_related('submitted_by'):
        uid=submission.submitted_by_id
        approved_counts[uid]=approved_counts.get(uid,0)+1
        if uid not in totals:
            totals[uid]={'user_id':uid,'username':submission.submitted_by.get_full_name() or submission.submitted_by.username,'points':0,'correct_answers':0,'attempts':0}
    for uid,row in totals.items():
        row['approved_contributions']=approved_counts.get(uid,0)
        row['contribution_points']=row['approved_contributions']*5
        row['points']+=row['contribution_points']
    global_rows=sorted(totals.values(),key=lambda row:(-row['points'],-row['correct_answers'],row['username'].lower()))
    for rank,row in enumerate(global_rows,1): row['rank']=rank
    per_question=[]
    # Keys include assessment ID as question IDs may be reused across assessments.
    for attempt in attempts:
        questions=attempt.assessment.questions or []
        for index,question in enumerate(questions):
            qid=str(question.get('id',index+1))
            bank_id = question.get('question_bank_id')
            if not bank_id or not QuestionSubmission.objects.filter(pk=bank_id, course=attempt.assessment.course, status='approved').exists():
                # Never show an assessment question in per-question rankings unless it
                # is represented by an approved Question Bank entry.
                continue
            if not (attempt.question_results or {}).get(qid,False): continue
            elapsed=(attempt.question_timings or {}).get(qid,(attempt.question_timings or {}).get(str(index+1),600000))
            try: elapsed=int(elapsed)
            except (TypeError,ValueError): elapsed=600000
            per_question.append({'question_key':f"{attempt.assessment_id}:{qid}",'question_id':qid,'assessment_id':attempt.assessment_id,'assessment_title':attempt.assessment.title,'course_title':attempt.assessment.course.title,'question_text':question.get('text','Question'),'student':attempt.trainee.get_full_name() or attempt.trainee.username,'user_id':attempt.trainee_id,'elapsed_ms':elapsed,'points':10+max(0,5-min(5,elapsed//6000)),'submitted_at':attempt.submitted_at})
    # Question Bank questions have their own stable IDs, separate from assessment IDs.
    for question_id, records in practice_by_question.items():
        question = records[0].question
        key = f'qb:{question_id}'
        for record in records:
            if not record.is_correct:
                continue
            per_question.append({'question_key': key, 'question_id': str(question_id), 'assessment_id': None,
                'assessment_title': 'Question Bank Practice', 'course_title': question.course.title if question.course else 'General',
                'question_text': question.question_text, 'student': record.trainee.get_full_name() or record.trainee.username,
                'user_id': record.trainee_id, 'elapsed_ms': 600000, 'points': record.points_earned,
                'submitted_at': record.first_correct_at or record.updated_at})
    per_question.sort(key=lambda row:(row['question_key'],-row['points'],row['elapsed_ms'],row['submitted_at']))
    grouped={}
    for row in per_question:
        group=grouped.setdefault(row['question_key'],{'question_key':row['question_key'],'question_id':row['question_id'],'assessment_id':row['assessment_id'],'assessment_title':row['assessment_title'],'course_title':row['course_title'],'question_text':row['question_text'],'entries':[]})
        if len(group['entries'])<10:
            group['entries'].append({k:row[k] for k in ['student','user_id','elapsed_ms','points','submitted_at']})
    return Response({'global':global_rows[:100],'per_question':list(grouped.values())})

@api_view(['GET'])
@permission_classes([IsAuthenticated,IsApproved,IsAdminRole])
def admin_overview(request):
    return Response({'users':User.objects.count(),'pending_users':User.objects.filter(is_approved=False).count(),'trainees':User.objects.filter(role='trainee').count(),'trainers':User.objects.filter(role='trainer').count(),'courses':Course.objects.count(),'assessments':Assessment.objects.count(),'attempts':Attempt.objects.count(),'average_score':round(Attempt.objects.aggregate(avg=Avg('score'))['avg'] or 0,1)})

class AdminUsersView(generics.ListAPIView):
    serializer_class=UserSerializer; permission_classes=[IsAuthenticated,IsApproved,IsAdminRole]
    def get_queryset(self):
        qs=User.objects.all().order_by('-date_joined')
        status_param=self.request.query_params.get('status')
        if status_param=='pending': qs=qs.filter(is_approved=False)
        elif status_param=='approved': qs=qs.filter(is_approved=True)
        return qs

@api_view(['POST'])
@permission_classes([IsAuthenticated,IsApproved,IsAdminRole])
def approve_user(request, user_id):
    try: user=User.objects.get(pk=user_id)
    except User.DoesNotExist: return Response({'detail':'User not found.'},status=404)
    if user.is_superuser: return Response({'detail':'Superuser is already approved.'},status=400)
    user.is_approved=True
    if request.data.get('role') in ['trainee','trainer']: user.role=request.data['role']
    user.save(update_fields=['is_approved','role'])
    return Response({'message':f'{user.username} approved.','user':UserSerializer(user).data})

@api_view(['POST'])
@permission_classes([IsAuthenticated,IsApproved,IsAdminRole])
def update_user_role(request,user_id):
    try: user=User.objects.get(pk=user_id)
    except User.DoesNotExist: return Response({'detail':'User not found.'},status=404)
    role=request.data.get('role')
    if role not in ['trainee','trainer','admin']: return Response({'detail':'Invalid role.'},status=400)
    if user.is_superuser: return Response({'detail':'Cannot change a superuser role here.'},status=400)
    user.role=role; user.save(update_fields=['role'])
    return Response(UserSerializer(user).data)

# Open learning platform: lectures, assignments, and course discussions.
from .models import CourseLesson, Assignment, AssignmentSubmission, CourseDiscussion
from .serializers import CourseLessonSerializer, AssignmentSerializer, AssignmentSubmissionSerializer, CourseDiscussionSerializer

class CourseLessonViewSet(viewsets.ModelViewSet):
    serializer_class = CourseLessonSerializer
    permission_classes = [IsAuthenticated, IsApproved]
    def get_queryset(self):
        qs = CourseLesson.objects.select_related('course','course__trainer').all()
        course_id = self.request.query_params.get('course')
        if course_id: qs = qs.filter(course_id=course_id)
        user = self.request.user
        if user.role == 'admin' or user.is_superuser: return qs
        # Trainers can also learn: show their own course content plus previews/enrolled courses.
        from django.db.models import Q
        if user.role == 'trainer': return qs.filter(Q(course__trainer=user) | Q(is_preview=True) | Q(course__enrollments__trainee=user)).distinct()
        return qs.filter(Q(is_preview=True) | Q(course__enrollments__trainee=user)).distinct()
    def get_permissions(self):
        if self.action in ['create','update','partial_update','destroy']:
            return [IsAuthenticated(), IsApproved(), IsTrainerOrAdmin()]
        return super().get_permissions()
    def perform_create(self, serializer):
        course = serializer.validated_data['course']
        if self.request.user.role == 'trainer' and course.trainer_id != self.request.user.id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('You can only add lectures to your own courses.')
        serializer.save()
    def update(self, request, *args, **kwargs):
        obj = self.get_object()
        if request.user.role == 'trainer' and obj.course.trainer_id != request.user.id:
            return Response({'detail':'You can only edit lectures in your own courses.'}, status=403)
        return super().update(request,*args,**kwargs)
    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        if request.user.role == 'trainer' and obj.course.trainer_id != request.user.id:
            return Response({'detail':'You can only delete lectures in your own courses.'}, status=403)
        return super().destroy(request,*args,**kwargs)

class AssignmentViewSet(viewsets.ModelViewSet):
    serializer_class = AssignmentSerializer
    permission_classes = [IsAuthenticated, IsApproved]
    def get_queryset(self):
        qs = Assignment.objects.select_related('course','course__trainer','created_by').annotate(submission_count=Count('submissions'))
        course_id=self.request.query_params.get('course')
        if course_id: qs=qs.filter(course_id=course_id)
        user = self.request.user
        if user.role == 'admin' or user.is_superuser: return qs
        if user.role == 'trainer':
            from django.db.models import Q
            return qs.filter(Q(course__trainer=user) | Q(is_published=True,course__enrollments__trainee=user)).distinct()
        return qs.filter(is_published=True, course__enrollments__trainee=user).distinct()
    def get_permissions(self):
        if self.action in ['create','update','partial_update','destroy']:
            return [IsAuthenticated(), IsApproved(), IsTrainerOrAdmin()]
        return super().get_permissions()
    def perform_create(self, serializer):
        course=serializer.validated_data['course']; user=self.request.user
        if user.role=='trainer' and course.trainer_id != user.id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('You can only create assignments for your own courses.')
        serializer.save(created_by=user)
    def update(self, request, *args, **kwargs):
        obj=self.get_object()
        if request.user.role=='trainer' and obj.course.trainer_id != request.user.id: return Response({'detail':'You can only edit your own assignments.'},status=403)
        return super().update(request,*args,**kwargs)
    def destroy(self, request, *args, **kwargs):
        obj=self.get_object()
        if request.user.role=='trainer' and obj.course.trainer_id != request.user.id: return Response({'detail':'You can only delete your own assignments.'},status=403)
        return super().destroy(request,*args,**kwargs)
    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        assignment=self.get_object(); user=request.user
        if user.role=='admin' or user.is_superuser: return Response({'detail':'Admin accounts do not submit learner assignments.'},status=403)
        if not Enrollment.objects.filter(trainee=user,course=assignment.course).exists(): return Response({'detail':'Enroll in this course before submitting.'},status=403)
        if assignment.due_at and timezone.now()>assignment.due_at: return Response({'detail':'The submission deadline has passed.'},status=400)
        if AssignmentSubmission.objects.filter(assignment=assignment,learner=user).exists(): return Response({'detail':'You have already submitted this assignment.'},status=409)
        serializer=AssignmentSubmissionSerializer(data=request.data,context={'request':request})
        serializer.is_valid(raise_exception=True)
        serializer.save(assignment=assignment,learner=user)
        return Response({'message':'Assignment submitted successfully.','submission':serializer.data},status=201)
    @action(detail=True, methods=['get'])
    def submissions(self, request, pk=None):
        assignment=self.get_object()
        if request.user.role not in ['trainer','admin'] and not request.user.is_superuser: return Response({'detail':'Only trainers can review submissions.'},status=403)
        if request.user.role=='trainer' and assignment.course.trainer_id != request.user.id: return Response({'detail':'You cannot review this assignment.'},status=403)
        qs=assignment.submissions.select_related('learner')
        return Response(AssignmentSubmissionSerializer(qs,many=True,context={'request':request}).data)

@api_view(['POST'])
@permission_classes([IsAuthenticated, IsApproved, IsTrainerOrAdmin])
def review_assignment_submission(request, submission_id):
    try: sub=AssignmentSubmission.objects.select_related('assignment__course').get(pk=submission_id)
    except AssignmentSubmission.DoesNotExist: return Response({'detail':'Submission not found.'},status=404)
    if request.user.role=='trainer' and sub.assignment.course.trainer_id != request.user.id:
        return Response({'detail':'You can only grade submissions for your own courses.'},status=403)
    score=request.data.get('score')
    try: score=int(score)
    except (TypeError,ValueError): return Response({'detail':'Score must be a whole number.'},status=400)
    if score < 0 or score > sub.assignment.max_score: return Response({'detail':f'Score must be between 0 and {sub.assignment.max_score}.'},status=400)
    sub.score=score; sub.feedback=str(request.data.get('feedback',''))[:5000]
    sub.status='revision' if request.data.get('request_revision') else 'reviewed'
    sub.reviewed_at=timezone.now(); sub.save(update_fields=['score','feedback','status','reviewed_at'])
    return Response({'message':'Feedback saved.','submission':AssignmentSubmissionSerializer(sub,context={'request':request}).data})

class AssignmentSubmissionListView(generics.ListAPIView):
    serializer_class=AssignmentSubmissionSerializer
    permission_classes=[IsAuthenticated,IsApproved]
    def get_queryset(self):
        user=self.request.user
        qs=AssignmentSubmission.objects.select_related('assignment','assignment__course','learner')
        if user.role=='trainee': return qs.filter(learner=user)
        if user.role=='trainer': return qs.filter(assignment__course__trainer=user)
        return qs

class CourseDiscussionViewSet(viewsets.ModelViewSet):
    serializer_class=CourseDiscussionSerializer
    permission_classes=[IsAuthenticated,IsApproved]
    http_method_names=['get','post','delete','head','options']
    def get_queryset(self):
        qs=CourseDiscussion.objects.select_related('course','author','course__trainer')
        course_id=self.request.query_params.get('course')
        if course_id: qs=qs.filter(course_id=course_id)
        user=self.request.user
        if user.role=='admin' or user.is_superuser: return qs
        if user.role=='trainer':
            from django.db.models import Q
            return qs.filter(Q(course__trainer=user) | Q(course__enrollments__trainee=user)).distinct()
        return qs.filter(course__enrollments__trainee=user).distinct()
    def create(self, request, *args, **kwargs):
        course_id=request.data.get('course')
        course=Course.objects.filter(pk=course_id).first()
        if not course: return Response({'detail':'Course not found.'},status=404)
        is_owner=course.trainer_id==request.user.id
        is_enrolled=Enrollment.objects.filter(course_id=course_id,trainee=request.user).exists()
        if not is_enrolled and not is_owner and request.user.role!='admin' and not request.user.is_superuser:
            return Response({'detail':'Enroll in the course to join its discussion.'},status=403)
        serializer=self.get_serializer(data=request.data); serializer.is_valid(raise_exception=True); serializer.save(author=request.user)
        return Response(serializer.data,status=201)
    def destroy(self, request, *args, **kwargs):
        obj=self.get_object()
        is_admin = request.user.role == 'admin' or request.user.is_superuser
        is_course_trainer = obj.course.trainer_id == request.user.id
        if obj.author_id != request.user.id and not is_admin and not is_course_trainer:
            return Response({'detail':'You can delete your own posts, or moderate posts in your own course.'},status=403)
        obj.delete(); return Response(status=204)
@api_view(['GET'])
@permission_classes([IsAuthenticated, IsApproved])
def learning_intelligence(request):
    from rest_framework.exceptions import ValidationError
    from .ai_service import get_learning_recommendations

    try:
        max_recommendations = int(request.query_params.get('limit', 5))
    except (TypeError, ValueError):
        raise ValidationError({
            'limit': 'Must be an integer between 1 and 20.'
        })

    if not 1 <= max_recommendations <= 20:
        raise ValidationError({
            'limit': 'Must be between 1 and 20.'
        })

    result = get_learning_recommendations(
        request.user,
        max_recommendations=max_recommendations
    )

    return Response(result.model_dump())

# ---------------------------------------------------------------------------
# Phase 3: PayPal webhook synchronization, refunds and financial reporting.
# ---------------------------------------------------------------------------

@api_view(['POST'])
@permission_classes([AllowAny])
def paypal_webhook(request):
    """Verify PayPal's signature before accepting or processing any event."""
    webhook_id = getattr(settings, 'PAYPAL_WEBHOOK_ID', '')
    if not webhook_id:
        return Response({'detail': 'PayPal webhook is not configured.'}, status=503)
    required_headers = {
        'auth_algo': request.headers.get('PayPal-Auth-Algo'),
        'cert_url': request.headers.get('PayPal-Cert-Url'),
        'transmission_id': request.headers.get('PayPal-Transmission-Id'),
        'transmission_sig': request.headers.get('PayPal-Transmission-Sig'),
        'transmission_time': request.headers.get('PayPal-Transmission-Time'),
    }
    if not all(required_headers.values()):
        return Response({'detail': 'Missing PayPal transmission headers.'}, status=400)
    try:
        verification = _paypal_verify_webhook_signature(required_headers, webhook_id, request.body)
    except Exception:
        logger.exception('PayPal webhook signature verification request failed')
        return Response({'detail': 'Webhook verification is temporarily unavailable.'}, status=502)
    if verification.get('verification_status') != 'SUCCESS':
        return Response({'detail': 'Invalid PayPal webhook signature.'}, status=400)

    event_id = str(request.data.get('id', '')).strip()
    event_type = str(request.data.get('event_type', '')).strip()
    resource = request.data.get('resource') or {}
    if not event_id or not event_type:
        return Response({'detail': 'Webhook event id and type are required.'}, status=400)
    event, created = PayPalWebhookEvent.objects.get_or_create(
        event_id=event_id,
        defaults={'event_type': event_type, 'resource_id': str(resource.get('id', '')), 'payload': request.data, 'status': 'received'},
    )
    if not created and event.status in ('processed', 'reconciliation_required'):
        return Response({
            'received': True,
            'duplicate': True,
            'reconciliation_required': event.status == 'reconciliation_required',
        }, status=200)

    try:
        with transaction.atomic():
            event = PayPalWebhookEvent.objects.select_for_update().get(pk=event.pk)
            if event.status == 'processed':
                return Response({'received': True, 'duplicate': True}, status=200)
            resource_id = str(resource.get('id', ''))
            related = resource.get('supplementary_data', {}).get('related_ids', {})
            # Refund resources carry the originating capture ID in related_ids too;
            # use it so a refund webhook can be processed even if it arrives first.
            capture_id = str(related.get('capture_id', '') or (resource_id if event_type.startswith('PAYMENT.CAPTURE.') else ''))
            order_id = str(related.get('order_id', '') or resource.get('invoice_id', ''))
            payment = Payment.objects.select_for_update().filter(paypal_capture_id=capture_id).first() if capture_id else None
            if payment is None and order_id:
                payment = Payment.objects.select_for_update().filter(paypal_order_id=order_id).first()
            if payment is None and (event_type.startswith('PAYMENT.REFUND.') or event_type == 'PAYMENT.CAPTURE.REFUNDED') and resource_id:
                prior_refund = Refund.objects.select_related('payment').filter(paypal_refund_id=resource_id).first()
                if prior_refund:
                    payment = Payment.objects.select_for_update().filter(pk=prior_refund.payment_id).first()

            if event_type in ('PAYMENT.CAPTURE.COMPLETED', 'PAYMENT.CAPTURE.DENIED', 'PAYMENT.REFUND.COMPLETED', 'PAYMENT.REFUND.PENDING', 'PAYMENT.REFUND.FAILED', 'PAYMENT.CAPTURE.REFUNDED', 'PAYMENT.CAPTURE.REVERSED') and payment is None:
                raise ValueError('No local payment matches the PayPal event resource.')

            if event_type == 'PAYMENT.CAPTURE.COMPLETED' and payment:
                amount = resource.get('amount') or {}
                if amount.get('currency_code') != payment.currency or Decimal(str(amount.get('value', '0'))) != payment.gross_amount:
                    raise ValueError('Webhook capture amount/currency does not match the stored order.')
                if payment.status == 'created':
                    capture_id = capture_id or resource.get('id')
                    if not capture_id:
                        raise ValueError('Completed capture event has no capture ID.')
                    fee_pct = _platform_fee_percent()
                    fee = (payment.gross_amount * fee_pct / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    payment.paypal_capture_id = capture_id
                    payment.platform_fee = fee
                    payment.trainer_share = payment.gross_amount - fee
                    payment.status = 'captured'
                    payment.captured_at = timezone.now()
                    payment.save(update_fields=['paypal_capture_id','platform_fee','trainer_share','status','captured_at'])
                    Enrollment.objects.get_or_create(trainee=payment.learner, course=payment.course)
            elif event_type == 'PAYMENT.REFUND.COMPLETED' and payment:
                amount = resource.get('amount') or {}
                refund_amount = Decimal(str(amount.get('value', '0')))
                if amount.get('currency_code') != payment.currency or refund_amount <= 0:
                    raise ValueError('Invalid refund amount/currency in webhook.')
                if refund_amount + payment.refunded_amount > payment.gross_amount:
                    raise ValueError('Refund total exceeds the original captured amount.')
                refund_id = resource_id
                refund, refund_created = Refund.objects.get_or_create(
                    paypal_refund_id=refund_id or None,
                    defaults={'payment': payment, 'amount': refund_amount, 'currency': payment.currency,
                              'status': 'completed', 'reason': 'PayPal refund webhook',
                              'created_by': None, 'completed_at': timezone.now()},
                )
                should_apply_refund = refund_created or refund.status != 'completed'
                if should_apply_refund:
                    refund.status = 'completed'
                    refund.amount = refund_amount
                    refund.currency = payment.currency
                    refund.completed_at = timezone.now()
                    refund.save(update_fields=['status','amount','currency','completed_at'])
                    payment.refunded_amount = min(payment.gross_amount, payment.refunded_amount + refund_amount)
                    if payment.refunded_amount >= payment.gross_amount:
                        payment.status = 'refunded'
                    payment.save(update_fields=['refunded_amount','status'])
                # Product policy: any completed refund, including a partial refund,
                # revokes course access for the learner and removes them from the trainer roster.
                if payment.refunded_amount > 0:
                    Enrollment.objects.filter(trainee=payment.learner, course=payment.course).delete()
                    WithdrawnEnrollment.objects.filter(trainee=payment.learner, course=payment.course).delete()
            elif event_type == 'PAYMENT.CAPTURE.REFUNDED' and payment:
                # This capture-level notification can arrive before the corresponding
                # PAYMENT.REFUND.COMPLETED event. It does not provide a reliable
                # per-refund amount/ID, so never synthesize a refund from it: doing so
                # would make the later refund-level event double-count the money.
                capture_status = str(resource.get('status', '')).upper()
                logger.info(
                    'Received capture refund event for payment %s; PayPal resource status: %s',
                    payment.id,
                    capture_status or 'not provided'
                )
                event.status = 'reconciliation_required'
                event.error = (
                    'Capture refund notification received; awaiting refund-level event '
                    'for the exact amount and refund ID.'
                )
                event.processed_at = timezone.now()
                event.save(update_fields=['status', 'error', 'processed_at'])
                Enrollment.objects.filter(trainee=payment.learner, course=payment.course).delete()
                WithdrawnEnrollment.objects.filter(trainee=payment.learner, course=payment.course).delete()
                return Response({
                    'received': True,
                    'reconciliation_required': True,
                    'detail': 'Capture refund acknowledged; exact refund amount will be applied from the refund-level event.',
                }, status=202)
            elif event_type == 'PAYMENT.CAPTURE.REVERSED' and payment:
                # Preserve reversal/chargeback visibility in the disputes ledger without falsely
                # classifying it as a customer-initiated refund.
                PayPalDispute.objects.update_or_create(
                    dispute_id=f'reversal-{event_id}',
                    defaults={'payment': payment, 'status': 'REVERSED',
                              'reason': 'PayPal capture reversal',
                              'amount': Decimal(str((resource.get('amount') or {}).get('value'))) if (resource.get('amount') or {}).get('value') else None,
                              'currency': str((resource.get('amount') or {}).get('currency_code', payment.currency))[:3],
                              'raw_payload': request.data},
                )
            elif event_type == 'PAYMENT.CAPTURE.DENIED' and payment and payment.status == 'created':
                payment.status = 'failed'
                payment.save(update_fields=['status'])
            elif event_type in ('PAYMENT.REFUND.PENDING', 'PAYMENT.REFUND.FAILED') and payment:
                refund_id = resource_id
                refund_status = 'pending' if event_type.endswith('PENDING') else 'failed'
                if refund_id:
                    Refund.objects.update_or_create(
                        paypal_refund_id=refund_id,
                        defaults={'payment': payment, 'amount': Decimal(str((resource.get('amount') or {}).get('value', '0'))),
                                  'currency': (resource.get('amount') or {}).get('currency_code', payment.currency),
                                  'status': refund_status, 'reason': 'PayPal refund webhook', 'created_by': None},
                    )
            elif event_type.startswith('PAYMENT.PAYOUTSBATCH.') or event_type.startswith('PAYMENT.PAYOUTS-ITEM.'):
                # PayPal sends batch-level and item-level payout notifications.
                # A batch SUCCESS alone is not enough to mark a single-item payout
                # complete; the item SUCCEEDED event is authoritative.
                batch_header = resource.get('batch_header') or {}
                payout_batch_id = str(
                    resource.get('payout_batch_id')
                    or batch_header.get('payout_batch_id')
                    or (resource.get('payout_item') or {}).get('payout_batch_id')
                    or ''
                )
                if payout_batch_id:
                    payout = Payout.objects.select_for_update().filter(
                        paypal_batch_id=payout_batch_id
                    ).first()
                    if payout:
                        if event_type.endswith('.SUCCEEDED'):
                            payout.status = 'completed'
                            payout.completed_at = timezone.now()
                            payout.failure_reason = ''
                            payout.save(update_fields=['status', 'completed_at', 'failure_reason', 'updated_at'])
                        elif event_type.endswith(('.FAILED', '.BLOCKED', '.RETURNED', '.CANCELED', '.DENIED')):
                            payout.status = 'failed'
                            payout.failure_reason = f'PayPal payout webhook: {event_type}'
                            payout.save(update_fields=['status', 'failure_reason', 'updated_at'])
                        elif event_type.endswith(('.PROCESSING', '.SUCCESS')):
                            # Keep the reservation until the payout item itself succeeds.
                            if payout.status not in ('completed', 'failed'):
                                payout.status = 'processing'
                                payout.save(update_fields=['status', 'updated_at'])

            elif event_type.startswith('CUSTOMER.DISPUTE.'):
                dispute_id = resource_id or str(resource.get('dispute_id', ''))
                disputed_transactions = resource.get('disputed_transactions') or []
                seller_transaction_id = ''
                if disputed_transactions:
                    seller_transaction_id = str(disputed_transactions[0].get('seller_transaction_id', ''))
                dispute_payment = payment
                if dispute_payment is None and seller_transaction_id:
                    dispute_payment = Payment.objects.select_for_update().filter(paypal_capture_id=seller_transaction_id).first()
                dispute_amount = resource.get('dispute_amount') or resource.get('amount') or {}
                evidence_details = resource.get('evidence_details') or {}
                due_date = parse_datetime(evidence_details.get('due_date', '')) if evidence_details.get('due_date') else None
                if dispute_id:
                    PayPalDispute.objects.update_or_create(
                        dispute_id=dispute_id,
                        defaults={'payment': dispute_payment, 'status': str(resource.get('status', event_type.rsplit('.', 1)[-1]))[:40],
                                  'reason': str(resource.get('reason', ''))[:120],
                                  'amount': Decimal(str(dispute_amount.get('value'))) if dispute_amount.get('value') else None,
                                  'currency': str(dispute_amount.get('currency_code', ''))[:3],
                                  'evidence_due_date': due_date, 'raw_payload': request.data},
                    )
            # Unknown events are retained for audit but intentionally do not mutate money.
            event.status = 'processed'
            event.processed_at = timezone.now()
            event.error = ''
            event.save(update_fields=['status','processed_at','error'])
    except Exception as exc:
        PayPalWebhookEvent.objects.filter(pk=event.pk).update(status='failed', error=str(exc)[:2000])
        logger.exception('Verified PayPal webhook event %s (%s) failed local processing', event_id, event_type)
        return Response({'detail': 'Webhook was verified but could not be processed. PayPal may retry delivery.'}, status=500)
    return Response({'received': True, 'duplicate': False}, status=200)



@transaction.atomic
@api_view(['POST'])
@permission_classes([IsAuthenticated, IsApproved, IsAdminRole])
def admin_refund_payment(request, payment_id):
    """Issue a full or partial PayPal refund; local totals update only after PayPal confirms it."""
    try:
        payment = Payment.objects.select_for_update().get(pk=payment_id)
    except Payment.DoesNotExist:
        return Response({'detail': 'Payment not found.'}, status=404)
    if payment.status not in ('captured', 'refunded') or not payment.paypal_capture_id:
        return Response({'detail': 'Only captured payments can be refunded.'}, status=409)
    try:
        amount = Decimal(str(request.data.get('amount', payment.gross_amount - payment.refunded_amount))).quantize(Decimal('0.01'))
    except Exception:
        return Response({'detail': 'A valid refund amount is required.'}, status=400)
    remaining = payment.gross_amount - payment.refunded_amount
    if amount <= 0 or amount > remaining:
        return Response({'detail': 'Refund amount must be greater than zero and no more than the remaining captured amount.'}, status=400)
    payload = {'amount': {'value': f'{amount:.2f}', 'currency_code': payment.currency}, 'note_to_payer': str(request.data.get('reason', 'Refund issued by Capacity Connect'))[:200]}
    try:
        result = _paypal_request(f'/v2/payments/captures/{payment.paypal_capture_id}/refund', 'POST', payload,
                                 request_id=f'cc-refund-{payment.id}-{amount}-{payment.refunded_amount}')
    except Exception as exc:
        return Response({'detail': f'PayPal refund failed: {str(exc)[:400]}'}, status=502)
    if not result.get('id'):
        return Response({'detail': 'PayPal did not return a refund ID.', 'paypal_status': result.get('status')}, status=502)
    paypal_status = result.get('status')
    if paypal_status not in ('COMPLETED', 'PENDING', 'FAILED'):
        return Response({'detail': 'Unexpected PayPal refund status.', 'paypal_status': paypal_status}, status=502)
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        local_status = paypal_status.lower()
        refund, created = Refund.objects.get_or_create(
            paypal_refund_id=result['id'],
            defaults={'payment': payment, 'amount': amount, 'currency': payment.currency,
                      'status': local_status, 'reason': str(request.data.get('reason', ''))[:500],
                      'created_by': request.user, 'completed_at': timezone.now() if paypal_status == 'COMPLETED' else None},
        )
        if created and paypal_status == 'COMPLETED':
            payment.refunded_amount = payment.refunded_amount + amount
            if payment.refunded_amount >= payment.gross_amount:
                payment.status = 'refunded'
            payment.save(update_fields=['refunded_amount','status'])
        if refund.status == 'completed' and payment.refunded_amount > 0:
            # Product policy: any confirmed refund revokes the learner's access.
            Enrollment.objects.filter(trainee=payment.learner, course=payment.course).delete()
            WithdrawnEnrollment.objects.filter(trainee=payment.learner, course=payment.course).delete()
    response_status = 201 if refund.status == 'completed' else (202 if refund.status == 'pending' else 502)
    return Response({'refund_id': refund.paypal_refund_id, 'status': refund.status,
                     'amount': str(refund.amount), 'currency': refund.currency,
                     'refunded_total': str(payment.refunded_amount),
                     'payment_status': payment.status}, status=response_status)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsApproved, IsAdminRole])
def admin_webhook_reconciliation_events(request):
    """List verified webhook events that need manual financial reconciliation."""
    events = PayPalWebhookEvent.objects.filter(
        status__in=['failed', 'reconciliation_required']
    ).order_by('-received_at')[:200]
    return Response([{
        'event_id': event.event_id,
        'event_type': event.event_type,
        'resource_id': event.resource_id,
        'status': event.status,
        'error': event.error,
        'received_at': event.received_at,
    } for event in events])


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsApproved, IsAdminRole])
def admin_paypal_disputes(request):
    disputes = PayPalDispute.objects.select_related('payment', 'payment__course').all()
    return Response([{
        'dispute_id': d.dispute_id,
        'payment_id': d.payment_id,
        'course_title': d.payment.course.title if d.payment_id else None,
        'status': d.status,
        'reason': d.reason,
        'amount': str(d.amount) if d.amount is not None else None,
        'currency': d.currency,
        'evidence_due_date': d.evidence_due_date,
        'updated_at': d.updated_at,
    } for d in disputes])


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsApproved, IsAdminRole])
def admin_financial_report(request):
    """Currency-separated financial totals; never adds unlike currencies together."""
    payments = Payment.objects.all()
    results = []
    currencies = payments.order_by().values_list('currency', flat=True).distinct()
    for currency in currencies:
        rows = payments.filter(currency=currency)
        captured = rows.filter(status__in=['captured','refunded'])
        gross = captured.aggregate(total=Sum('gross_amount'))['total'] or Decimal('0.00')
        refunded = rows.aggregate(total=Sum('refunded_amount'))['total'] or Decimal('0.00')
        fee_total = Decimal('0.00')
        share_total = Decimal('0.00')
        for payment in captured.select_related('course'):
            _, net_fee, net_share = _payment_net_financials(payment)
            fee_total += net_fee
            share_total += net_share
        results.append({'currency': currency, 'gross_captured': str(Decimal(gross).quantize(Decimal('0.01'))), 'refunded': str(Decimal(refunded).quantize(Decimal('0.01'))),
                        'net_after_refunds': str((Decimal(gross)-Decimal(refunded)).quantize(Decimal('0.01'))), 'platform_fee_net': str(fee_total),
                        'trainer_share_net': str(share_total), 'payment_count': rows.count()})
    return Response({'by_currency': results})


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsApproved, IsAdminRole])
def admin_reconcile_payments(request):
    """Read-only reconciliation against PayPal capture details for a supplied set of local captures."""
    payment_ids = request.query_params.getlist('payment_id')
    qs = Payment.objects.exclude(paypal_capture_id__isnull=True).exclude(paypal_capture_id='')
    if payment_ids:
        qs = qs.filter(pk__in=payment_ids)
    qs = qs.order_by('-captured_at')[:100]
    rows = []
    for payment in qs:
        try:
            remote = _paypal_request(f'/v2/payments/captures/{payment.paypal_capture_id}')
            remote_amount = remote.get('amount') or {}
            remote_value = Decimal(str(remote_amount.get('value', '0')))
            local_value = payment.gross_amount
            rows.append({'payment_id': payment.id, 'capture_id': payment.paypal_capture_id,
                         'local_status': payment.status, 'paypal_status': remote.get('status'),
                         'local_gross_amount': str(local_value), 'local_refunded_amount': str(payment.refunded_amount), 'paypal_capture_amount': str(remote_value),
                         'currency_match': remote_amount.get('currency_code') == payment.currency,
                         'amount_match': remote_value == local_value,
                         'match': remote_amount.get('currency_code') == payment.currency and remote_value == local_value})
        except Exception as exc:
            rows.append({'payment_id': payment.id, 'capture_id': payment.paypal_capture_id,
                         'match': False, 'error': str(exc)[:300]})
    return Response({'checked': len(rows), 'results': rows})


# Phase 4: Trainer earnings, withdrawal requests and PayPal Payouts.
def _trainer_payout_balances(trainer):
    """Calculate trainer entitlement from net sales after refunds and platform fees."""
    totals = {}
    payments = Payment.objects.filter(
        course__trainer=trainer, status__in=('captured', 'refunded')
    ).select_related('course')
    for payment in payments:
        currency = payment.currency.upper()
        row = totals.setdefault(currency, {
            'currency': currency,
            'gross_sales': Decimal('0.00'),
            'refunded': Decimal('0.00'),
            'net_sales': Decimal('0.00'),
            'platform_fee': Decimal('0.00'),
            'earned': Decimal('0.00'),
            'disputed': Decimal('0.00'),
            'reserved': Decimal('0.00'),
            'paid': Decimal('0.00'),
        })
        net_amount, net_fee, net_share = _payment_net_financials(payment)
        row['gross_sales'] += payment.gross_amount
        row['refunded'] += payment.refunded_amount
        row['net_sales'] += net_amount
        row['platform_fee'] += net_fee
        row['earned'] += net_share
        # Disputed amounts are unavailable until PayPal explicitly resolves
        # the case in the seller's favour. A buyer-favourable/unknown outcome
        # remains withheld to avoid paying out money that may be clawed back.
        for dispute in payment.disputes.all():
            dispute_status = str(dispute.status or '').upper()
            outcome = str(
                (dispute.raw_payload.get('dispute_outcome') or {}).get('outcome_code', '')
            ).upper() if isinstance(dispute.raw_payload, dict) else ''
            seller_won = (
                'SELLER_FAVOUR' in outcome or 'SELLER_FAVOR' in outcome
                or dispute_status in ('WON', 'RESOLVED_SELLER_FAVOR', 'RESOLVED_SELLER_FAVOUR')
            )
            if seller_won or not dispute.amount or dispute.currency.upper() != currency:
                continue
            disputed_gross = min(Decimal(dispute.amount), net_amount)
            if net_amount > 0:
                row['disputed'] += (disputed_gross * net_share / net_amount).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP
                )

    payouts = Payout.objects.filter(trainer=trainer)
    for payout in payouts:
        currency = payout.currency.upper()
        row = totals.setdefault(currency, {
            'currency': currency,
            'gross_sales': Decimal('0.00'),
            'refunded': Decimal('0.00'),
            'net_sales': Decimal('0.00'),
            'platform_fee': Decimal('0.00'),
            'earned': Decimal('0.00'),
            'disputed': Decimal('0.00'),
            'reserved': Decimal('0.00'),
            'paid': Decimal('0.00'),
        })
        if payout.status in ('pending', 'approved', 'processing'):
            row['reserved'] += payout.amount
        elif payout.status == 'completed':
            row['paid'] += payout.amount

    result = []
    for row in totals.values():
        # Refunds reduce net sales first; the platform fee is then calculated
        # proportionally on the remaining sale. Trainer entitlement is the
        # remainder after that fee, not the gross payment's original share.
        row['available'] = max(
            Decimal('0.00'), row['earned'] - row['disputed'] - row['reserved'] - row['paid']
        )
        row['adjustment_due'] = max(
            Decimal('0.00'), row['disputed'] + row['reserved'] + row['paid'] - row['earned']
        )
        result.append({
            key: (str(value.quantize(Decimal('0.01'))) if isinstance(value, Decimal) else value)
            for key, value in row.items()
        })
    return sorted(result, key=lambda item: item['currency'])


def _serialize_payout(payout):
    return {
        'id': payout.id, 'trainer_id': payout.trainer_id,
        'trainer_name': payout.trainer.get_full_name() or payout.trainer.username,
        'trainer_email': payout.trainer.email, 'paypal_email': payout.trainer.paypal_email,
        'amount': str(payout.amount), 'currency': payout.currency, 'status': payout.status,
        'paypal_batch_id': payout.paypal_batch_id, 'sender_batch_id': payout.sender_batch_id, 'created_at': payout.created_at,
        'completed_at': payout.completed_at, 'rejection_reason': payout.rejection_reason,
        'failure_reason': payout.failure_reason,
    }


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, IsApproved])
def trainer_payouts(request):
    if request.user.role != 'trainer' or request.user.is_superuser:
        return Response({'detail': 'Only approved trainer accounts can access trainer payouts.'}, status=403)
    if request.method == 'GET':
        payouts = Payout.objects.filter(trainer=request.user).order_by('-created_at')
        return Response({'balances': _trainer_payout_balances(request.user), 'paypal_email': request.user.paypal_email, 'payouts': [_serialize_payout(p) for p in payouts]})
    if not request.user.paypal_email:
        return Response({'detail': 'Add your PayPal email in Profile before requesting a payout.'}, status=400)
    try:
        amount = Decimal(str(request.data.get('amount', '')).strip()).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return Response({'detail': 'Enter a valid payout amount.'}, status=400)
    # Decimal('NaN') parses successfully, but comparisons with it raise
    # InvalidOperation and used to turn malformed requests into HTTP 500s.
    if not amount.is_finite():
        return Response({'detail': 'Enter a finite payout amount.'}, status=400)
    currency = str(request.data.get('currency', '')).upper().strip()
    if amount <= 0 or len(currency) != 3 or not currency.isalpha():
        return Response({'detail': 'A positive amount and valid three-letter currency are required.'}, status=400)
    with transaction.atomic():
        # Serialize requests per trainer so two concurrent requests cannot reserve the same earnings.
        User.objects.select_for_update().get(pk=request.user.pk)
        balance = next((row for row in _trainer_payout_balances(request.user) if row['currency'] == currency), None)
        available = Decimal(balance['available']) if balance else Decimal('0.00')
        if amount > available:
            return Response({'detail': f'Insufficient available balance. Available: {available} {currency}.'}, status=400)
        payout = Payout.objects.create(trainer=request.user, amount=amount, currency=currency, status='pending')
    return Response({'message': 'Payout request submitted for administrator approval.', 'payout': _serialize_payout(payout)}, status=201)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, IsApproved, IsAdminRole])
def admin_trainer_payouts(request):
    if request.method == 'GET':
        qs = Payout.objects.select_related('trainer').order_by('-created_at')
        status_filter = request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return Response([_serialize_payout(p) for p in qs[:500]])
    payout_id = request.data.get('payout_id')
    action_name = str(request.data.get('action', '')).lower()
    with transaction.atomic():
        try:
            payout = Payout.objects.select_for_update().select_related('trainer').get(pk=payout_id)
        except (Payout.DoesNotExist, TypeError, ValueError):
            return Response({'detail': 'Payout request not found.'}, status=404)
        if action_name == 'approve':
            if payout.status != 'pending':
                return Response({'detail': 'Only pending payout requests can be approved.'}, status=409)
            payout.status = 'approved'; payout.processed_by = request.user; payout.save(update_fields=['status','processed_by','updated_at'])
            return Response({'message': 'Payout request approved.', 'payout': _serialize_payout(payout)})
        if action_name == 'reject':
            if payout.status != 'pending':
                return Response({'detail': 'Only pending payout requests can be rejected.'}, status=409)
            reason = str(request.data.get('reason', '')).strip()
            if not reason:
                return Response({'detail': 'A rejection reason is required.'}, status=400)
            payout.status = 'rejected'; payout.rejection_reason = reason[:500]; payout.processed_by = request.user
            payout.save(update_fields=['status','rejection_reason','processed_by','updated_at'])
            return Response({'message': 'Payout request rejected.', 'payout': _serialize_payout(payout)})
        if action_name != 'process':
            return Response({'detail': 'Action must be approve, reject or process.'}, status=400)
        # Recovery path: if the original POST timed out after PayPal may have
        # accepted it, retry the exact same batch with the same sender_batch_id.
        # PayPal's idempotency key prevents creating a second transfer.
        recovery_retry = (
            payout.status == 'processing'
            and not payout.paypal_batch_id
            and bool(payout.sender_batch_id)
        )
        if payout.status != 'approved' and not recovery_retry:
            if payout.status == 'processing' and payout.paypal_batch_id:
                return Response({
                    'detail': 'This payout already has a PayPal batch ID. Synchronize its status instead of resubmitting.',
                    'paypal_batch_id': payout.paypal_batch_id,
                }, status=409)
            return Response({'detail': 'Approve this payout request before processing it, or retry an ambiguous processing request.'}, status=409)
        if not payout.trainer.paypal_email:
            return Response({'detail': 'Trainer has not configured a PayPal email.'}, status=400)
        if payout.status == 'approved':
            balance = next((row for row in _trainer_payout_balances(payout.trainer) if row['currency'] == payout.currency.upper()), None)
            if balance:
                # This approved payout itself is included in reserved; exclude it
                # when checking whether current net earnings still cover it.
                other_reserved = Decimal(balance['reserved']) - payout.amount
                payable_now = max(Decimal('0.00'), Decimal(balance['earned']) - Decimal(balance['paid']) - other_reserved)
            else:
                payable_now = Decimal('0.00')
            if payout.amount > payable_now:
                payout.status = 'failed'
                payout.failure_reason = (
                    "Payout cancelled before submission because refunds reduced the trainer's "
                    f'net earnings. Current payable amount: {payable_now} {payout.currency}.'
                )
                payout.save(update_fields=['status', 'failure_reason', 'updated_at'])
                return Response({
                    "detail": "Payout was not sent because refunds reduced the trainer's available net earnings. The reservation has been released.",
                    'payout': _serialize_payout(payout),
                }, status=409)
        if not payout.sender_batch_id:
            payout.sender_batch_id = f'CCPAYOUT{payout.pk:010d}'
        payout.status = 'processing'; payout.processed_by = request.user
        payout.save(update_fields=['sender_batch_id','status','processed_by','updated_at'])
    # Call PayPal outside the database transaction. The stable sender_batch_id makes safe retries possible.
    payload = {
        'sender_batch_header': {
            'sender_batch_id': payout.sender_batch_id,
            'email_subject': 'Your CAPACITY CONNECT trainer payout',
            'email_message': 'Your approved trainer earnings are being sent.',
        },
        'items': [{
            'recipient_type': 'EMAIL', 'receiver': payout.trainer.paypal_email,
            'amount': {'value': format(payout.amount, '.2f'), 'currency': payout.currency},
            'note': f'CAPACITY CONNECT trainer payout #{payout.id}',
            'sender_item_id': f'CCPAYOUTITEM{payout.id}',
        }],
    }
    try:
        result = _paypal_request('/v1/payments/payouts', method='POST', payload=payload, request_id=payout.sender_batch_id)
        batch = result.get('batch_header') or {}
        payout.paypal_batch_id = batch.get('payout_batch_id') or payout.paypal_batch_id
        batch_status = str(batch.get('batch_status', '')).upper()
        if batch_status == 'DENIED':
            payout.status = 'failed'; payout.failure_reason = 'PayPal denied the payout batch.'
        else:
            payout.status = 'processing'
            payout.failure_reason = '' if payout.paypal_batch_id else 'PayPal response did not include a payout batch ID; retry with the same sender batch ID.'
        payout.save(update_fields=['paypal_batch_id','status','failure_reason','updated_at'])
        if not payout.paypal_batch_id:
            logger.error('PayPal payout response omitted batch ID for local payout %s', payout.pk)
            return Response({'detail': 'PayPal response could not be linked to a payout batch. The request remains reserved; retry using the same payout request.', 'payout': _serialize_payout(payout)}, status=502)
        return Response({'message': 'Payout submitted to PayPal.', 'paypal_batch_status': batch_status, 'payout': _serialize_payout(payout)}, status=202)
    except urllib.error.HTTPError as exc:
        raw_error = exc.read().decode(errors='replace')
        detail = raw_error[:900]
        # A duplicate sender_batch_id response can include a HATEOAS link to the
        # original batch. Recover only the batch ID from that link; never follow
        # an arbitrary URL supplied in an error response.
        if exc.code == 409:
            try:
                error_payload = json.loads(raw_error)
                stack = [error_payload]
                while stack:
                    node = stack.pop()
                    if isinstance(node, dict):
                        href = node.get('href')
                        if isinstance(href, str):
                            match = re.search(r'/v1/payments/payouts/([^/?#]+)', href)
                            if match:
                                payout.paypal_batch_id = match.group(1)
                                payout.save(update_fields=['paypal_batch_id','updated_at'])
                                break
                        stack.extend(node.values())
                    elif isinstance(node, list):
                        stack.extend(node)
            except (ValueError, TypeError):
                pass
        # HTTP 409 can mean PayPal already received this sender_batch_id. Keep
        # funds reserved. If its original-batch link was present, admins can sync.
        if 400 <= exc.code < 500 and exc.code != 409:
            payout.status = 'failed'
            payout.failure_reason = f'PayPal rejected payout ({exc.code}): {detail}'
            payout.save(update_fields=['status','failure_reason','updated_at'])
            logger.warning('PayPal definitively rejected payout %s (HTTP %s)', payout.pk, exc.code)
            return Response({'detail': 'PayPal rejected the payout request. The reserved balance has been released.', 'payout': _serialize_payout(payout)}, status=502)
        payout.failure_reason = f'PayPal response {exc.code}: {detail}'
        payout.save(update_fields=['failure_reason','updated_at'])
        logger.warning('Ambiguous PayPal payout response for payout %s (HTTP %s)', payout.pk, exc.code)
        return Response({'detail': 'PayPal payout submission could not be confirmed. The request remains reserved; retry with the same payout request or reconcile it.', 'payout': _serialize_payout(payout)}, status=502)
    except Exception:
        # Do not expose credentials, URLs, or raw transport details to the client.
        payout.failure_reason = 'Network or unexpected error while submitting payout; outcome is unknown.'
        payout.save(update_fields=['failure_reason','updated_at'])
        logger.exception('Ambiguous PayPal payout submission failure for payout %s', payout.pk)
        return Response({'detail': 'PayPal payout submission could not be confirmed. The request remains reserved; retry with the same payout request or reconcile it.', 'payout': _serialize_payout(payout)}, status=502)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsApproved, IsAdminRole])
def admin_sync_trainer_payout(request, payout_id):
    try:
        payout = Payout.objects.select_related('trainer').get(pk=payout_id)
    except Payout.DoesNotExist:
        return Response({'detail': 'Payout not found.'}, status=404)
    if not payout.paypal_batch_id:
        return Response({'detail': 'This payout has not been submitted to PayPal yet.'}, status=400)
    try:
        result = _paypal_request(f'/v1/payments/payouts/{payout.paypal_batch_id}?fields=all')
    except Exception as exc:
        return Response({'detail': f'Could not retrieve PayPal payout status: {str(exc)[:300]}'}, status=502)
    batch = result.get('batch_header') or {}
    batch_status = str(batch.get('batch_status', '')).upper()
    items = result.get('items') or []
    item_status = str((items[0] or {}).get('transaction_status', '')).upper() if items else ''
    with transaction.atomic():
        payout = Payout.objects.select_for_update().get(pk=payout.pk)
        if batch_status == 'SUCCESS' and item_status == 'SUCCESS':
            payout.status = 'completed'; payout.completed_at = timezone.now(); payout.failure_reason = ''
        elif batch_status in ('DENIED', 'CANCELED') or item_status in ('FAILED', 'DENIED', 'RETURNED', 'BLOCKED'):
            payout.status = 'failed'; payout.failure_reason = f"PayPal batch/item status: {batch_status}/{item_status or 'unknown'}"
        elif batch_status in ('PENDING', 'PROCESSING', 'ONHOLD', 'SUCCESS'):
            # A successful batch can still contain an unclaimed/held item. Keep funds reserved until the item succeeds.
            payout.status = 'processing'
        payout.save(update_fields=['status','completed_at','failure_reason','updated_at'])
    return Response({'paypal_batch_status': batch_status, 'paypal_item_status': item_status, 'payout': _serialize_payout(payout)})
