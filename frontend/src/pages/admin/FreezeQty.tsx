import { ArrowLeft, Pencil, Plus, Save, Search, Snowflake, Trash2, Upload, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { adminApi } from '@/api/admin'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { FreezeQty } from '@/types/admin'

const EXCHANGES = ['NFO', 'BFO', 'CDS', 'MCX']

export default function FreezeQtyPage() {
  const [freezeData, setFreezeData] = useState<FreezeQty[]>([])
  const [filteredData, setFilteredData] = useState<FreezeQty[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')

  // Add dialog state
  const [showAddDialog, setShowAddDialog] = useState(false)
  const [newEntry, setNewEntry] = useState({ exchange: 'NFO', symbol: '', freeze_qty: '' })
  const [isAdding, setIsAdding] = useState(false)

  // Edit state
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editValue, setEditValue] = useState('')
  const [isSaving, setIsSaving] = useState(false)

  // Delete dialog state
  const [deleteEntry, setDeleteEntry] = useState<FreezeQty | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)

  // Upload dialog state
  const [showUploadDialog, setShowUploadDialog] = useState(false)
  const [uploadExchange, setUploadExchange] = useState('NFO')
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [isUploading, setIsUploading] = useState(false)

  useEffect(() => {
    fetchFreezeData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (searchQuery) {
      const filtered = freezeData.filter(
        (item) =>
          item.symbol.toLowerCase().includes(searchQuery.toLowerCase()) ||
          item.exchange.toLowerCase().includes(searchQuery.toLowerCase())
      )
      setFilteredData(filtered)
    } else {
      setFilteredData(freezeData)
    }
  }, [searchQuery, freezeData])

  const fetchFreezeData = async () => {
    try {
      const data = await adminApi.getFreezeList()
      setFreezeData(data)
      setFilteredData(data)
    } catch (error) {
      showToast.error('Failed to load freeze quantities', 'admin')
    } finally {
      setIsLoading(false)
    }
  }

  const handleAdd = async () => {
    if (!newEntry.symbol || !newEntry.freeze_qty) {
      showToast.error('Please fill in all fields', 'admin')
      return
    }

    setIsAdding(true)
    try {
      const response = await adminApi.addFreeze({
        exchange: newEntry.exchange,
        symbol: newEntry.symbol.toUpperCase(),
        freeze_qty: parseInt(newEntry.freeze_qty, 10),
      })

      if (response.status === 'success') {
        showToast.success(response.message || 'Entry added successfully', 'admin')
        setShowAddDialog(false)
        setNewEntry({ exchange: 'NFO', symbol: '', freeze_qty: '' })
        fetchFreezeData()
      } else {
        showToast.error(response.message || 'Failed to add entry', 'admin')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } }
      showToast.error(err.response?.data?.message || 'Failed to add entry', 'admin')
    } finally {
      setIsAdding(false)
    }
  }

  const handleEdit = (entry: FreezeQty) => {
    setEditingId(entry.id)
    setEditValue(entry.freeze_qty.toString())
  }

  const handleSaveEdit = async (id: number) => {
    if (!editValue) {
      showToast.error('Please enter a freeze quantity', 'admin')
      return
    }

    setIsSaving(true)
    try {
      const response = await adminApi.editFreeze(id, {
        freeze_qty: parseInt(editValue, 10),
      })

      if (response.status === 'success') {
        showToast.success(response.message || 'Entry updated successfully', 'admin')
        setEditingId(null)
        fetchFreezeData()
      } else {
        showToast.error(response.message || 'Failed to update entry', 'admin')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } }
      showToast.error(err.response?.data?.message || 'Failed to update entry', 'admin')
    } finally {
      setIsSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!deleteEntry) return

    setIsDeleting(true)
    try {
      const response = await adminApi.deleteFreeze(deleteEntry.id)

      if (response.status === 'success') {
        showToast.success(response.message || 'Entry deleted successfully', 'admin')
        setDeleteEntry(null)
        fetchFreezeData()
      } else {
        showToast.error(response.message || 'Failed to delete entry', 'admin')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } }
      showToast.error(err.response?.data?.message || 'Failed to delete entry', 'admin')
    } finally {
      setIsDeleting(false)
    }
  }

  const handleUpload = async () => {
    if (!uploadFile) {
      showToast.error('Please select a CSV file', 'admin')
      return
    }

    setIsUploading(true)
    try {
      const response = await adminApi.uploadFreezeCSV(uploadFile, uploadExchange)

      if (response.status === 'success') {
        showToast.success(response.message || 'CSV uploaded successfully', 'admin')
        setShowUploadDialog(false)
        setUploadFile(null)
        fetchFreezeData()
      } else {
        showToast.error(response.message || 'Failed to upload CSV', 'admin')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } }
      showToast.error(err.response?.data?.message || 'Failed to upload CSV', 'admin')
    } finally {
      setIsUploading(false)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <Link to="/admin" className="text-muted-foreground hover:text-foreground">
              <ArrowLeft className="h-4 w-4" />
            </Link>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <Snowflake className="h-6 w-6" />
              Freeze Quantities
            </h1>
          </div>
          <p className="text-muted-foreground">
            Manage F&O freeze quantity limits for automatic order splitting
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setShowUploadDialog(true)}>
            <Upload className="h-4 w-4 mr-2" />
            Upload CSV
          </Button>
          <Button onClick={() => setShowAddDialog(true)}>
            <Plus className="h-4 w-4 mr-2" />
            Add Entry
          </Button>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold">{freezeData.length}</p>
            <p className="text-sm text-muted-foreground">Total Symbols</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold">
              {freezeData.filter((f) => f.exchange === 'NFO').length}
            </p>
            <p className="text-sm text-muted-foreground">NFO Symbols</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold">
              {freezeData.filter((f) => f.exchange !== 'NFO').length}
            </p>
            <p className="text-sm text-muted-foreground">Other Exchanges</p>
          </CardContent>
        </Card>
      </div>

      {/* Search and Table */}
      <Card>
        <CardHeader>
          <CardTitle>Freeze Quantity List</CardTitle>
          <CardDescription>{filteredData.length} entries total</CardDescription>
        </CardHeader>
        <CardContent>
          {/* Search */}
          <div className="flex items-center gap-2 mb-4">
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search by symbol or exchange..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9"
              />
            </div>
          </div>

          {/* Table */}
          <div className="border rounded-md">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Exchange</TableHead>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Freeze Qty</TableHead>
                  <TableHead className="w-[100px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredData.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={4} className="text-center text-muted-foreground py-8">
                      {searchQuery
                        ? 'No matching entries found'
                        : 'No freeze quantities configured'}
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredData.map((entry) => (
                    <TableRow key={entry.id}>
                      <TableCell className="font-medium">{entry.exchange}</TableCell>
                      <TableCell>{entry.symbol}</TableCell>
                      <TableCell>
                        {editingId === entry.id ? (
                          <div className="flex items-center gap-2">
                            <Input
                              type="number"
                              value={editValue}
                              onChange={(e) => setEditValue(e.target.value)}
                              className="w-24 h-8"
                              min={1}
                              aria-label={`Freeze quantity for ${entry.symbol}`}
                            />
                            <Button
                              size="icon"
                              variant="ghost"
                              className="h-8 w-8"
                              onClick={() => handleSaveEdit(entry.id)}
                              disabled={isSaving}
                            >
                              <Save className="h-4 w-4" />
                            </Button>
                            <Button
                              size="icon"
                              variant="ghost"
                              className="h-8 w-8"
                              onClick={() => setEditingId(null)}
                            >
                              <X className="h-4 w-4" />
                            </Button>
                          </div>
                        ) : (
                          entry.freeze_qty.toLocaleString()
                        )}
                      </TableCell>
                      <TableCell>
                        {editingId !== entry.id && (
                          <div className="flex items-center gap-1">
                            <Button
                              size="icon"
                              variant="ghost"
                              className="h-8 w-8"
                              onClick={() => handleEdit(entry)}
                            >
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button
                              size="icon"
                              variant="ghost"
                              className="h-8 w-8 text-destructive hover:text-destructive"
                              onClick={() => setDeleteEntry(entry)}
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </div>
                        )}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Add Dialog */}
      <Dialog open={showAddDialog} onOpenChange={setShowAddDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Freeze Quantity</DialogTitle>
            <DialogDescription>
              Add a new freeze quantity entry for an F&O symbol.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Exchange</Label>
              <Select
                value={newEntry.exchange}
                onValueChange={(value) => setNewEntry({ ...newEntry, exchange: value })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {EXCHANGES.map((ex) => (
                    <SelectItem key={ex} value={ex}>
                      {ex}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Symbol</Label>
              <Input
                placeholder="e.g., NIFTY, RELIANCE"
                value={newEntry.symbol}
                onChange={(e) => setNewEntry({ ...newEntry, symbol: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>Freeze Quantity</Label>
              <Input
                type="number"
                placeholder="e.g., 1800"
                value={newEntry.freeze_qty}
                onChange={(e) => setNewEntry({ ...newEntry, freeze_qty: e.target.value })}
                min={1}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAddDialog(false)}>
              Cancel
            </Button>
            <Button onClick={handleAdd} disabled={isAdding}>
              {isAdding ? 'Adding...' : 'Add Entry'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Upload Dialog */}
      <Dialog open={showUploadDialog} onOpenChange={setShowUploadDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Upload Freeze Quantities CSV</DialogTitle>
            <DialogDescription>
              Upload a CSV file to bulk update freeze quantities. This will replace existing entries
              for the selected exchange.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Exchange</Label>
              <Select value={uploadExchange} onValueChange={setUploadExchange}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {EXCHANGES.map((ex) => (
                    <SelectItem key={ex} value={ex}>
                      {ex}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>CSV File</Label>
              <Input
                type="file"
                accept=".csv"
                onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
              />
              <p className="text-xs text-muted-foreground">
                CSV should have columns: SYMBOL, VOL_FRZ_QTY (or FRZ_QTY)
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowUploadDialog(false)}>
              Cancel
            </Button>
            <Button onClick={handleUpload} disabled={isUploading || !uploadFile}>
              {isUploading ? 'Uploading...' : 'Upload'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={!!deleteEntry} onOpenChange={() => setDeleteEntry(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Entry?</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete the freeze quantity for {deleteEntry?.symbol} (
              {deleteEntry?.exchange})? This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} disabled={isDeleting}>
              {isDeleting ? 'Deleting...' : 'Delete'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
