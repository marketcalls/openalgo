/**
 * Confirm before logging in to another broker, which ends the live broker
 * session when that sign-in completes (or before saving new keys for the
 * logged-in broker, which ends its session at once), as OpenAlgo Desktop does.
 *
 * Keys can be saved for many brokers, but only one broker is logged in at a
 * time. Select Broker asks first, naming what stops and what stays.
 */

import { AlertTriangle } from 'lucide-react'
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

interface BrokerSwitchConfirmProps {
  /** The broker whose session ends (display name); null closes the dialog. */
  from: string | null
  /** The broker being logged in to (display name). */
  to: string
  /**
   * What ends the session: logging in to `to` (the default), or saving new
   * keys for `from` itself (a session belongs to the keys it signed in
   * with).
   */
  cause?: 'login' | 'new-keys'
  onCancel: () => void
  onConfirm: () => void
}

export function BrokerSwitchConfirm({
  from,
  to,
  cause = 'login',
  onCancel,
  onConfirm,
}: BrokerSwitchConfirmProps) {
  const newKeys = cause === 'new-keys'
  return (
    <AlertDialog
      open={from !== null}
      onOpenChange={(open) => {
        if (!open) onCancel()
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-yellow-500" />
            End your {from} session?
          </AlertDialogTitle>
          <AlertDialogDescription asChild>
            <div className="space-y-3">
              <p>
                {newKeys ? `Saving new keys for ${from}` : `Signing in to ${to}`} ends your {from}{' '}
                session. Open positions and orders stay with {from}.
              </p>
              <p>
                OpenAlgo stops placing stop-loss and target exits for {from}, and your trading
                platforms and API clients can no longer trade through it. Close or protect open
                positions at {from} first if you need to.{' '}
                {newKeys
                  ? `Log in to ${from} again to use the new keys.`
                  : `Your ${from} session ends only when the sign-in to ${to} completes; if it does not, ${from} stays connected. Your ${from} keys stay saved, so switching back needs only a login.`}
              </p>
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={onCancel}>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>
            {newKeys ? 'End session and save' : `Log in to ${to}`}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
