from rest_framework.permissions import BasePermission, SAFE_METHODS
class IsApproved(BasePermission):
    message = 'Your account is awaiting administrator approval.'
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and (request.user.is_approved or request.user.is_superuser))
class IsAdminRole(BasePermission):
    def has_permission(self, request, view): return bool(request.user and request.user.is_authenticated and (request.user.is_superuser or request.user.role == 'admin'))
class IsTrainerOrAdmin(BasePermission):
    def has_permission(self, request, view): return bool(request.user and request.user.is_authenticated and (request.user.is_superuser or request.user.role in ['trainer','admin']))
