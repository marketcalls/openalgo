import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  Users,
  ArrowLeft,
  Trash2,
  Send,
  Bell,
  BellOff,
  Search,
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
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { toast } from 'sonner';
import { webClient } from '@/api/client';
import type { TelegramUser, CommandStats } from '@/types/telegram';

export default function TelegramUsers() {
  const [users, setUsers] = useState<TelegramUser[]>([]);
  const [filteredUsers, setFilteredUsers] = useState<TelegramUser[]>([]);
  const [stats, setStats] = useState<CommandStats[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [isLoading, setIsLoading] = useState(true);

  // Message dialog state
  const [messageUser, setMessageUser] = useState<TelegramUser | null>(null);
  const [messageText, setMessageText] = useState('');
  const [isSending, setIsSending] = useState(false);

  // Unlink dialog state
  const [unlinkUser, setUnlinkUser] = useState<TelegramUser | null>(null);
  const [isUnlinking, setIsUnlinking] = useState(false);

  useEffect(() => {
    fetchUsers();
  }, []);

  useEffect(() => {
    if (searchQuery) {
      const filtered = users.filter(
        (user) =>
          user.telegram_username?.toLowerCase().includes(searchQuery.toLowerCase()) ||
          user.openalgo_username?.toLowerCase().includes(searchQuery.toLowerCase()) ||
          user.first_name?.toLowerCase().includes(searchQuery.toLowerCase())
      );
      setFilteredUsers(filtered);
    } else {
      setFilteredUsers(users);
    }
  }, [searchQuery, users]);

  const fetchUsers = async () => {
    try {
      const response = await webClient.get<{ status: string; data: { users: TelegramUser[]; stats: CommandStats[] } }>(
        '/telegram/api/users'
      );
      const fetchedUsers = Array.isArray(response.data.data?.users) ? response.data.data.users : [];
      const fetchedStats = Array.isArray(response.data.data?.stats) ? response.data.data.stats : [];
      setUsers(fetchedUsers);
      setFilteredUsers(fetchedUsers);
      setStats(fetchedStats);
    } catch (error) {
      console.error('Error fetching users:', error);
      toast.error('Failed to load users');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSendMessage = async () => {
    if (!messageUser || !messageText.trim()) {
      toast.error('Please enter a message');
      return;
    }

    setIsSending(true);
    try {
      const response = await webClient.post<{ status: string; message: string }>('/telegram/send-message', {
        telegram_id: messageUser.telegram_id,
        message: messageText,
      });

      if (response.data.status === 'success') {
        toast.success('Message sent successfully');
        setMessageUser(null);
        setMessageText('');
      } else {
        toast.error(response.data.message || 'Failed to send message');
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } };
      toast.error(err.response?.data?.message || 'Failed to send message');
    } finally {
      setIsSending(false);
    }
  };

  const handleUnlink = async () => {
    if (!unlinkUser) return;

    setIsUnlinking(true);
    try {
      const response = await webClient.post<{ status: string; message: string }>(
        `/telegram/user/${unlinkUser.telegram_id}/unlink`
      );

      if (response.data.status === 'success') {
        toast.success('User unlinked successfully');
        setUnlinkUser(null);
        fetchUsers();
      } else {
        toast.error(response.data.message || 'Failed to unlink user');
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } };
      toast.error(err.response?.data?.message || 'Failed to unlink user');
    } finally {
      setIsUnlinking(false);
    }
  };

  const formatDate = (dateString: string | null) => {
    if (!dateString) return '-';
    return new Date(dateString).toLocaleString();
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
      <div>
        <div className="flex items-center gap-2 mb-2">
          <Link to="/telegram" className="text-muted-foreground hover:text-foreground">
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Users className="h-6 w-6" />
            Telegram Users
          </h1>
        </div>
        <p className="text-muted-foreground">
          Manage users linked to the Telegram bot
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold">{users.length}</p>
            <p className="text-sm text-muted-foreground">Total Users</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold">
              {users.filter((u) => u.notifications_enabled).length}
            </p>
            <p className="text-sm text-muted-foreground">Notifications On</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold">
              {users.filter((u) => u.openalgo_username).length}
            </p>
            <p className="text-sm text-muted-foreground">Linked Accounts</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold">
              {stats.reduce((sum, s) => sum + s.count, 0)}
            </p>
            <p className="text-sm text-muted-foreground">Commands (30d)</p>
          </CardContent>
        </Card>
      </div>

      {/* Users Table */}
      <Card>
        <CardHeader>
          <CardTitle>User List</CardTitle>
          <CardDescription>
            {filteredUsers.length} users total
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* Search */}
          <div className="flex items-center gap-2 mb-4">
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search by username..."
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
                  <TableHead>Telegram User</TableHead>
                  <TableHead>OpenAlgo Account</TableHead>
                  <TableHead>Notifications</TableHead>
                  <TableHead>Joined</TableHead>
                  <TableHead>Last Active</TableHead>
                  <TableHead className="w-[100px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredUsers.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                      {searchQuery ? 'No matching users found' : 'No users registered yet'}
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredUsers.map((user) => (
                    <TableRow key={user.telegram_id}>
                      <TableCell>
                        <div>
                          <p className="font-medium">
                            {user.telegram_username ? `@${user.telegram_username}` : user.first_name || 'Unknown'}
                          </p>
                          <p className="text-xs text-muted-foreground">ID: {user.telegram_id}</p>
                        </div>
                      </TableCell>
                      <TableCell>
                        {user.openalgo_username ? (
                          <Badge variant="outline">{user.openalgo_username}</Badge>
                        ) : (
                          <span className="text-muted-foreground">Not linked</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {user.notifications_enabled ? (
                          <Badge className="bg-green-500 hover:bg-green-600">
                            <Bell className="h-3 w-3 mr-1" />
                            On
                          </Badge>
                        ) : (
                          <Badge variant="secondary">
                            <BellOff className="h-3 w-3 mr-1" />
                            Off
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-sm">{formatDate(user.created_at)}</TableCell>
                      <TableCell className="text-sm">{formatDate(user.last_active)}</TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1">
                          <Button
                            size="icon"
                            variant="ghost"
                            className="h-8 w-8"
                            onClick={() => {
                              setMessageUser(user);
                              setMessageText('');
                            }}
                            title="Send message"
                          >
                            <Send className="h-4 w-4" />
                          </Button>
                          <Button
                            size="icon"
                            variant="ghost"
                            className="h-8 w-8 text-destructive hover:text-destructive"
                            onClick={() => setUnlinkUser(user)}
                            title="Unlink user"
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Send Message Dialog */}
      <Dialog open={!!messageUser} onOpenChange={() => setMessageUser(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Send Message</DialogTitle>
            <DialogDescription>
              Send a message to {messageUser?.telegram_username ? `@${messageUser.telegram_username}` : messageUser?.first_name}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Message</Label>
              <Textarea
                placeholder="Enter your message..."
                value={messageText}
                onChange={(e) => setMessageText(e.target.value)}
                rows={4}
              />
              <p className="text-xs text-muted-foreground">
                {messageText.length}/4096 characters
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setMessageUser(null)}>
              Cancel
            </Button>
            <Button onClick={handleSendMessage} disabled={isSending || !messageText.trim()}>
              {isSending ? 'Sending...' : 'Send Message'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Unlink Confirmation Dialog */}
      <AlertDialog open={!!unlinkUser} onOpenChange={() => setUnlinkUser(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Unlink User?</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to unlink{' '}
              {unlinkUser?.telegram_username ? `@${unlinkUser.telegram_username}` : unlinkUser?.first_name}? They will
              need to re-register with /start to receive notifications again.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleUnlink} disabled={isUnlinking}>
              {isUnlinking ? 'Unlinking...' : 'Unlink'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
