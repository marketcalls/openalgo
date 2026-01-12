import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  Calendar,
  Plus,
  Trash2,
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { toast } from 'sonner';
import { adminApi } from '@/api/admin';
import type { Holiday } from '@/types/admin';

const HOLIDAY_TYPES = [
  { value: 'TRADING_HOLIDAY', label: 'Trading Holiday' },
  { value: 'SETTLEMENT_HOLIDAY', label: 'Settlement Holiday' },
  { value: 'SPECIAL_SESSION', label: 'Special Session' },
];

export default function HolidaysPage() {
  const [holidays, setHolidays] = useState<Holiday[]>([]);
  const [years, setYears] = useState<number[]>([]);
  const [exchanges, setExchanges] = useState<string[]>([]);
  const [currentYear, setCurrentYear] = useState(new Date().getFullYear());
  const [isLoading, setIsLoading] = useState(true);

  // Add dialog state
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [newHoliday, setNewHoliday] = useState<{
    date: string;
    description: string;
    holiday_type: 'TRADING_HOLIDAY' | 'SETTLEMENT_HOLIDAY' | 'SPECIAL_SESSION';
    closed_exchanges: string[];
  }>({
    date: '',
    description: '',
    holiday_type: 'TRADING_HOLIDAY',
    closed_exchanges: [],
  });
  const [isAdding, setIsAdding] = useState(false);

  // Delete dialog state
  const [deleteHoliday, setDeleteHoliday] = useState<Holiday | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    fetchHolidays(currentYear);
  }, [currentYear]);

  const fetchHolidays = async (year: number) => {
    setIsLoading(true);
    try {
      const response = await adminApi.getHolidays(year);
      setHolidays(response.data);
      setYears(response.years);
      setExchanges(response.exchanges);
    } catch (error) {
      console.error('Error fetching holidays:', error);
      toast.error('Failed to load holidays');
    } finally {
      setIsLoading(false);
    }
  };

  const handleAdd = async () => {
    if (!newHoliday.date || !newHoliday.description) {
      toast.error('Please fill in date and description');
      return;
    }

    if (newHoliday.holiday_type === 'TRADING_HOLIDAY' && newHoliday.closed_exchanges.length === 0) {
      toast.error('Please select at least one exchange to close');
      return;
    }

    setIsAdding(true);
    try {
      const response = await adminApi.addHoliday({
        date: newHoliday.date,
        description: newHoliday.description,
        holiday_type: newHoliday.holiday_type,
        closed_exchanges: newHoliday.closed_exchanges,
      });

      if (response.status === 'success') {
        toast.success(response.message || 'Holiday added successfully');
        setShowAddDialog(false);
        setNewHoliday({
          date: '',
          description: '',
          holiday_type: 'TRADING_HOLIDAY',
          closed_exchanges: [],
        });
        fetchHolidays(currentYear);
      } else {
        toast.error(response.message || 'Failed to add holiday');
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } };
      toast.error(err.response?.data?.message || 'Failed to add holiday');
    } finally {
      setIsAdding(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteHoliday) return;

    setIsDeleting(true);
    try {
      const response = await adminApi.deleteHoliday(deleteHoliday.id);

      if (response.status === 'success') {
        toast.success(response.message || 'Holiday deleted successfully');
        setDeleteHoliday(null);
        fetchHolidays(currentYear);
      } else {
        toast.error(response.message || 'Failed to delete holiday');
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } };
      toast.error(err.response?.data?.message || 'Failed to delete holiday');
    } finally {
      setIsDeleting(false);
    }
  };

  const toggleExchange = (exchange: string) => {
    setNewHoliday((prev) => ({
      ...prev,
      closed_exchanges: prev.closed_exchanges.includes(exchange)
        ? prev.closed_exchanges.filter((e) => e !== exchange)
        : [...prev.closed_exchanges, exchange],
    }));
  };

  const selectAllExchanges = () => {
    setNewHoliday((prev) => ({
      ...prev,
      closed_exchanges: exchanges,
    }));
  };

  const getHolidayTypeBadge = (type: string) => {
    switch (type) {
      case 'TRADING_HOLIDAY':
        return <Badge variant="destructive">Trading Holiday</Badge>;
      case 'SETTLEMENT_HOLIDAY':
        return <Badge variant="secondary">Settlement Holiday</Badge>;
      case 'SPECIAL_SESSION':
        return <Badge className="bg-purple-500 hover:bg-purple-600">Special Session</Badge>;
      default:
        return <Badge variant="outline">{type}</Badge>;
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    );
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
              <Calendar className="h-6 w-6" />
              Market Holidays
            </h1>
          </div>
          <p className="text-muted-foreground">
            Manage trading holidays for all supported exchanges
          </p>
        </div>
        <Button onClick={() => setShowAddDialog(true)}>
          <Plus className="h-4 w-4 mr-2" />
          Add Holiday
        </Button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold">{holidays.length}</p>
            <p className="text-sm text-muted-foreground">Total Holidays ({currentYear})</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold">
              {holidays.filter((h) => h.holiday_type === 'TRADING_HOLIDAY').length}
            </p>
            <p className="text-sm text-muted-foreground">Trading Holidays</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold">
              {holidays.filter((h) => h.holiday_type !== 'TRADING_HOLIDAY').length}
            </p>
            <p className="text-sm text-muted-foreground">Special Days</p>
          </CardContent>
        </Card>
      </div>

      {/* Year Selector */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle>Holiday Calendar</CardTitle>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="icon"
                onClick={() => setCurrentYear((y) => y - 1)}
                disabled={!years.includes(currentYear - 1)}
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Select
                value={currentYear.toString()}
                onValueChange={(v) => setCurrentYear(parseInt(v))}
              >
                <SelectTrigger className="w-[120px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {years.map((year) => (
                    <SelectItem key={year} value={year.toString()}>
                      {year}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                variant="outline"
                size="icon"
                onClick={() => setCurrentYear((y) => y + 1)}
                disabled={!years.includes(currentYear + 1)}
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
          <CardDescription>
            {holidays.length} holidays in {currentYear}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* Table */}
          <div className="border rounded-md">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>Day</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Closed Exchanges</TableHead>
                  <TableHead className="w-[80px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {holidays.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                      No holidays configured for {currentYear}
                    </TableCell>
                  </TableRow>
                ) : (
                  holidays.map((holiday) => (
                    <TableRow key={holiday.id}>
                      <TableCell className="font-medium">{holiday.date}</TableCell>
                      <TableCell>{holiday.day_name}</TableCell>
                      <TableCell>{holiday.description}</TableCell>
                      <TableCell>{getHolidayTypeBadge(holiday.holiday_type)}</TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          {holiday.closed_exchanges.length === 0 ? (
                            <span className="text-muted-foreground text-sm">-</span>
                          ) : (
                            holiday.closed_exchanges.map((ex) => (
                              <Badge key={ex} variant="outline" className="text-xs">
                                {ex}
                              </Badge>
                            ))
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-8 w-8 text-destructive hover:text-destructive"
                          onClick={() => setDeleteHoliday(holiday)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
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
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Add Holiday</DialogTitle>
            <DialogDescription>
              Add a new market holiday entry.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Date</Label>
              <Input
                type="date"
                value={newHoliday.date}
                onChange={(e) => setNewHoliday({ ...newHoliday, date: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>Description</Label>
              <Input
                placeholder="e.g., Republic Day"
                value={newHoliday.description}
                onChange={(e) => setNewHoliday({ ...newHoliday, description: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>Holiday Type</Label>
              <Select
                value={newHoliday.holiday_type}
                onValueChange={(value: 'TRADING_HOLIDAY' | 'SETTLEMENT_HOLIDAY' | 'SPECIAL_SESSION') =>
                  setNewHoliday({ ...newHoliday, holiday_type: value })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {HOLIDAY_TYPES.map((type) => (
                    <SelectItem key={type.value} value={type.value}>
                      {type.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {newHoliday.holiday_type === 'TRADING_HOLIDAY' && (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label>Closed Exchanges</Label>
                  <Button variant="link" size="sm" className="h-auto p-0" onClick={selectAllExchanges}>
                    Select All
                  </Button>
                </div>
                <div className="grid grid-cols-4 gap-2">
                  {exchanges.map((exchange) => (
                    <div key={exchange} className="flex items-center space-x-2">
                      <Checkbox
                        id={exchange}
                        checked={newHoliday.closed_exchanges.includes(exchange)}
                        onCheckedChange={() => toggleExchange(exchange)}
                      />
                      <label
                        htmlFor={exchange}
                        className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
                      >
                        {exchange}
                      </label>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAddDialog(false)}>
              Cancel
            </Button>
            <Button onClick={handleAdd} disabled={isAdding}>
              {isAdding ? 'Adding...' : 'Add Holiday'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={!!deleteHoliday} onOpenChange={() => setDeleteHoliday(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Holiday?</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete &quot;{deleteHoliday?.description}&quot; on{' '}
              {deleteHoliday?.date}? This action cannot be undone.
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
  );
}
