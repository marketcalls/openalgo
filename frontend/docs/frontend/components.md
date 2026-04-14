# Component Documentation

This document covers the UI components used in the OpenAlgo frontend.

## Component Architecture

```
components/
├── auth/           # Authentication components
├── layout/         # Layout components
└── ui/             # Base UI components (shadcn/ui)
```

## Layout Components

### Layout

Main application layout with navbar, content area, and footer.

```tsx
import { Layout } from '@/components/layout/Layout'

// Used in App.tsx for protected routes
<Route element={<Layout />}>
  <Route path="/dashboard" element={<Dashboard />} />
</Route>
```

**Features:**
- Responsive navbar with desktop/mobile variants
- Mobile bottom navigation (visible on `< md` screens)
- Footer with version info and social links
- Safe area padding for notched devices

### Navbar

Top navigation bar with logo, navigation links, and user menu.

```tsx
import { Navbar } from '@/components/layout/Navbar'
```

**Features:**
- Desktop: Horizontal navigation links
- Mobile: Hamburger menu with slide-out sheet
- Mode toggle (Live/Analyze)
- Theme toggle (Light/Dark)
- Profile dropdown menu
- Broker badge display

### MobileBottomNav

Fixed bottom navigation for mobile devices.

```tsx
import { MobileBottomNav } from '@/components/layout/MobileBottomNav'
```

**Navigation Items:**
1. Dashboard
2. Orderbook
3. Tradebook
4. Positions
5. Strategy

**Accessibility:**
- 44px minimum touch targets
- `touch-manipulation` for instant response
- Active state indication
- Safe area bottom padding

### Footer

Application footer with links and version info.

```tsx
import { Footer } from '@/components/layout/Footer'

<Footer className="custom-class" />
```

**Features:**
- Copyright and website link
- Version badge (fetched from API)
- Social media links (GitHub, Discord, X, YouTube)

### FullWidthLayout

Alternative layout without sidebar constraints.

```tsx
<Route element={<FullWidthLayout />}>
  <Route path="/playground" element={<Playground />} />
</Route>
```

## UI Components (shadcn/ui)

All base UI components are from [shadcn/ui](https://ui.shadcn.com/) with Radix UI primitives.

### Button

```tsx
import { Button } from '@/components/ui/button'

// Variants
<Button variant="default">Primary</Button>
<Button variant="secondary">Secondary</Button>
<Button variant="outline">Outline</Button>
<Button variant="ghost">Ghost</Button>
<Button variant="link">Link</Button>
<Button variant="destructive">Destructive</Button>

// Sizes
<Button size="default">Default</Button>
<Button size="sm">Small</Button>
<Button size="lg">Large</Button>
<Button size="icon">Icon</Button>

// With icon
<Button>
  <Plus className="h-4 w-4 mr-2" />
  Add Item
</Button>

// Icon-only (always add aria-label!)
<Button size="icon" aria-label="Open menu">
  <Menu className="h-4 w-4" />
</Button>

// As child (renders as anchor)
<Button asChild>
  <Link to="/dashboard">Go to Dashboard</Link>
</Button>
```

### Card

```tsx
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from '@/components/ui/card'

<Card>
  <CardHeader>
    <CardTitle>Card Title</CardTitle>
    <CardDescription>Card description text</CardDescription>
  </CardHeader>
  <CardContent>
    <p>Card content goes here</p>
  </CardContent>
  <CardFooter>
    <Button>Action</Button>
  </CardFooter>
</Card>
```

### Input

```tsx
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

<div className="space-y-2">
  <Label htmlFor="email">Email</Label>
  <Input
    id="email"
    type="email"
    placeholder="Enter your email"
    value={email}
    onChange={(e) => setEmail(e.target.value)}
  />
</div>
```

### Select

```tsx
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

<Select value={value} onValueChange={setValue}>
  <SelectTrigger>
    <SelectValue placeholder="Select option" />
  </SelectTrigger>
  <SelectContent>
    <SelectItem value="option1">Option 1</SelectItem>
    <SelectItem value="option2">Option 2</SelectItem>
  </SelectContent>
</Select>
```

### Dialog

```tsx
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogFooter,
} from '@/components/ui/dialog'

<Dialog open={open} onOpenChange={setOpen}>
  <DialogTrigger asChild>
    <Button>Open Dialog</Button>
  </DialogTrigger>
  <DialogContent>
    <DialogHeader>
      <DialogTitle>Dialog Title</DialogTitle>
      <DialogDescription>Dialog description</DialogDescription>
    </DialogHeader>
    <div>Dialog content</div>
    <DialogFooter>
      <Button onClick={() => setOpen(false)}>Close</Button>
    </DialogFooter>
  </DialogContent>
</Dialog>
```

### Sheet (Mobile Drawer)

```tsx
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'

<Sheet>
  <SheetTrigger asChild>
    <Button variant="ghost" size="icon" aria-label="Open menu">
      <Menu className="h-5 w-5" />
    </Button>
  </SheetTrigger>
  <SheetContent side="left">
    <SheetHeader>
      <SheetTitle>Menu</SheetTitle>
    </SheetHeader>
    <nav>...</nav>
  </SheetContent>
</Sheet>
```

### DropdownMenu

```tsx
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

<DropdownMenu>
  <DropdownMenuTrigger asChild>
    <Button variant="ghost" size="icon" aria-label="Open user menu">
      <User className="h-4 w-4" />
    </Button>
  </DropdownMenuTrigger>
  <DropdownMenuContent align="end">
    <DropdownMenuItem onSelect={() => navigate('/profile')}>
      Profile
    </DropdownMenuItem>
    <DropdownMenuSeparator />
    <DropdownMenuItem onSelect={handleLogout}>
      Logout
    </DropdownMenuItem>
  </DropdownMenuContent>
</DropdownMenu>
```

### Tabs

```tsx
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

<Tabs defaultValue="tab1">
  <TabsList>
    <TabsTrigger value="tab1">Tab 1</TabsTrigger>
    <TabsTrigger value="tab2">Tab 2</TabsTrigger>
  </TabsList>
  <TabsContent value="tab1">Content 1</TabsContent>
  <TabsContent value="tab2">Content 2</TabsContent>
</Tabs>
```

### Alert

```tsx
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { AlertTriangle, Info } from 'lucide-react'

// Info alert
<Alert>
  <Info className="h-4 w-4" />
  <AlertTitle>Information</AlertTitle>
  <AlertDescription>This is an info message.</AlertDescription>
</Alert>

// Destructive alert
<Alert variant="destructive">
  <AlertTriangle className="h-4 w-4" />
  <AlertTitle>Error</AlertTitle>
  <AlertDescription>Something went wrong.</AlertDescription>
</Alert>
```

### Badge

```tsx
import { Badge } from '@/components/ui/badge'

<Badge>Default</Badge>
<Badge variant="secondary">Secondary</Badge>
<Badge variant="outline">Outline</Badge>
<Badge variant="destructive">Destructive</Badge>
```

### Skeleton

```tsx
import { Skeleton } from '@/components/ui/skeleton'

// Loading placeholder
<div className="space-y-2">
  <Skeleton className="h-4 w-[250px]" />
  <Skeleton className="h-4 w-[200px]" />
</div>

// Card skeleton
<Card>
  <CardHeader>
    <Skeleton className="h-6 w-32" />
  </CardHeader>
  <CardContent>
    <Skeleton className="h-24 w-full" />
  </CardContent>
</Card>
```

### Toast (Sonner)

```tsx
import { toast } from 'sonner'

// Success
toast.success('Operation completed successfully')

// Error
toast.error('Something went wrong')

// Warning
toast.warning('Please check your input')

// With description
toast.success('Saved', {
  description: 'Your changes have been saved.',
})

// With action
toast('Event created', {
  action: {
    label: 'Undo',
    onClick: () => undoAction(),
  },
})
```

## Custom Components

### PageLoader

Full-page loading spinner for lazy-loaded routes.

```tsx
import { PageLoader } from '@/components/ui/page-loader'

// Used in App.tsx Suspense fallback
<Suspense fallback={<PageLoader />}>
  <Routes>...</Routes>
</Suspense>
```

### AuthSync

Syncs authentication state on app load.

```tsx
import { AuthSync } from '@/components/auth/AuthSync'

// Wraps the app in App.tsx
<AuthSync>
  <Routes>...</Routes>
</AuthSync>
```

## Component Patterns

### Loading States

```tsx
function MyComponent() {
  const [loading, setLoading] = useState(true)

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-32 w-full" />
      </div>
    )
  }

  return <div>Content</div>
}
```

### Error States

```tsx
function MyComponent() {
  const [error, setError] = useState<string | null>(null)

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertTriangle className="h-4 w-4" />
        <AlertTitle>Error</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    )
  }

  return <div>Content</div>
}
```

### Empty States

```tsx
function MyList({ items }) {
  if (items.length === 0) {
    return (
      <Card className="py-12">
        <CardContent className="flex flex-col items-center text-center">
          <Inbox className="h-12 w-12 text-muted-foreground mb-4" />
          <h3 className="text-lg font-semibold mb-2">No items</h3>
          <p className="text-muted-foreground mb-4">
            Get started by creating your first item.
          </p>
          <Button>Create Item</Button>
        </CardContent>
      </Card>
    )
  }

  return <div>{/* List content */}</div>
}
```

### Form Pattern

```tsx
function MyForm() {
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsLoading(true)
    try {
      await submitData()
      toast.success('Saved successfully')
    } catch (error) {
      toast.error('Failed to save')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="name">Name</Label>
        <Input id="name" required />
      </div>
      <Button type="submit" disabled={isLoading}>
        {isLoading ? (
          <>
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            Saving...
          </>
        ) : (
          'Save'
        )}
      </Button>
    </form>
  )
}
```

## Accessibility Guidelines

### Icon Buttons

Always add `aria-label` to icon-only buttons:

```tsx
// Good
<Button size="icon" aria-label="Open menu">
  <Menu className="h-4 w-4" />
</Button>

// Bad - no accessible name
<Button size="icon">
  <Menu className="h-4 w-4" />
</Button>
```

### Form Labels

Always associate labels with inputs:

```tsx
// Good
<Label htmlFor="email">Email</Label>
<Input id="email" type="email" />

// Bad - no association
<Label>Email</Label>
<Input type="email" />
```

### Focus Management

Ensure focus is visible and logical:

```tsx
// Button has built-in focus styles
<Button>Focusable</Button>

// Custom focus styles if needed
<div
  tabIndex={0}
  className="focus:outline-none focus:ring-2 focus:ring-primary"
>
  Focusable div
</div>
```

### Color Contrast

Use semantic color tokens that ensure contrast:

```tsx
// Good - uses theme tokens
<p className="text-foreground">Primary text</p>
<p className="text-muted-foreground">Secondary text</p>

// Avoid - may have contrast issues
<p className="text-gray-400">Low contrast text</p>
```
