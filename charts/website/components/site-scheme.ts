import { useEffect, useState } from 'react';
import { useTheme } from 'next-themes';

/**
 * The page's resolved theme, or null until the component has mounted.
 *
 * The static export renders before the reader's theme is known, and hydration
 * keeps the server's attributes rather than repairing them, so an iframe `src`
 * or a class chosen from the theme during render would stay on the server's
 * guess. Markup that depends on the theme reads it from here instead.
 */
export function useSiteScheme(): 'light' | 'dark' | null {
  const { resolvedTheme } = useTheme();
  const [scheme, setScheme] = useState<'light' | 'dark' | null>(null);
  useEffect(() => {
    setScheme(resolvedTheme === 'dark' ? 'dark' : 'light');
  }, [resolvedTheme]);
  return scheme;
}
