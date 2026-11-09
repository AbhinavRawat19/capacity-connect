import React, { useMemo, useState } from 'react'
import { AgGridReact } from 'ag-grid-react'
import { AllCommunityModule, ModuleRegistry, themeQuartz } from 'ag-grid-community'
import { Search } from 'lucide-react'

// Register once (AG Grid v33+ is modular). Community features only.
ModuleRegistry.registerModules([AllCommunityModule])

// Match the application's dark slate / lime palette (see index.css).
const gridTheme = themeQuartz.withParams({
  browserColorScheme: 'dark',
  backgroundColor: '#0c1627',
  foregroundColor: '#e2e8f0',
  headerBackgroundColor: '#111d30',
  headerTextColor: '#94a3b8',
  borderColor: '#1e293b',
  accentColor: '#a3e635',
  oddRowBackgroundColor: 'rgba(17,29,48,.55)',
  rowHoverColor: 'rgba(163,230,53,.06)',
  fontFamily: 'inherit',
  fontSize: 14,
  headerFontSize: 12,
  headerFontWeight: 700,
  borderRadius: 12,
  wrapperBorderRadius: 12,
})

function UserCell({ data }) {
  return <div className="flex h-full flex-col justify-center leading-tight"><span className="font-semibold text-white">{data.username}</span>{(data.first_name || data.last_name) && <span className="text-xs text-slate-500">{`${data.first_name || ''} ${data.last_name || ''}`.trim()}</span>}</div>
}
function RoleCell({ value }) {
  return <span className="badge capitalize">{value}</span>
}
function StatusCell({ value }) {
  return <span className={value === 'Active' ? 'badge badge-green' : 'badge badge-yellow'}>{value}</span>
}
// Same two actions, same callbacks and endpoints as the previous card list.
function ActionsCell({ data, context }) {
  return <div className="flex h-full items-center gap-2">
    {!data.is_approved && <button type="button" disabled={context.busy} onClick={() => context.onApprove(data)} className="btn btn-primary !px-3 !py-1.5 text-xs disabled:opacity-60">Approve</button>}
    <button type="button" disabled={context.busy} onClick={() => context.onChangeRole(data)} className="btn btn-secondary !px-3 !py-1.5 text-xs disabled:opacity-60">Change role</button>
  </div>
}

export default function AdminUsersGrid({ users, busy = false, onApprove, onChangeRole }) {
  const [quickFilter, setQuickFilter] = useState('')
  const columnDefs = useMemo(() => [
    { headerName: 'User', field: 'username', cellRenderer: UserCell, minWidth: 180, flex: 1.2, filter: 'agTextColumnFilter', getQuickFilterText: p => `${p.data.username} ${p.data.first_name || ''} ${p.data.last_name || ''}` },
    { headerName: 'Email', field: 'email', valueFormatter: p => p.value || 'No email', minWidth: 200, flex: 1.4, filter: 'agTextColumnFilter' },
    { headerName: 'Role', field: 'role', cellRenderer: RoleCell, minWidth: 120, flex: 0.7, filter: 'agTextColumnFilter' },
    { headerName: 'Status', colId: 'status', valueGetter: p => (p.data.is_approved ? 'Active' : 'Pending'), cellRenderer: StatusCell, minWidth: 120, flex: 0.7, filter: 'agTextColumnFilter' },
    { headerName: 'Joined', field: 'date_joined', valueFormatter: p => (p.value ? new Date(p.value).toLocaleDateString() : '—'), minWidth: 120, flex: 0.7, sort: 'desc' },
    { headerName: 'Actions', colId: 'actions', cellRenderer: ActionsCell, sortable: false, filter: false, minWidth: 210, flex: 1, getQuickFilterText: () => '' },
  ], [])
  const defaultColDef = useMemo(() => ({ sortable: true, resizable: true, filter: true }), [])
  const context = useMemo(() => ({ busy, onApprove, onChangeRole }), [busy, onApprove, onChangeRole])

  return <div data-testid="admin-users-grid">
    <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
      <div className="relative flex-1">
        <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" size={17} />
        <input className="field pl-10" placeholder="Search users by name, email or role…" aria-label="Search users" value={quickFilter} onChange={e => setQuickFilter(e.target.value)} />
      </div>
      <span className="badge self-start sm:self-center">{users.length} users</span>
    </div>
    <AgGridReact
      theme={gridTheme}
      rowData={users}
      columnDefs={columnDefs}
      defaultColDef={defaultColDef}
      getRowId={p => String(p.data.id)}
      quickFilterText={quickFilter}
      context={context}
      pagination
      paginationPageSize={10}
      paginationPageSizeSelector={[10, 25, 50]}
      rowHeight={56}
      domLayout="autoHeight"
      suppressCellFocus
      overlayNoRowsTemplate="No users match the current filters."
    />
  </div>
}
