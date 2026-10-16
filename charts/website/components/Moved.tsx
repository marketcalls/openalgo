import React, { useEffect } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import { useRouter } from 'next/router';

/**
 * Sends a retired URL to the section that replaced it. A static export cannot
 * answer with a server redirect, and links to the old page are already out in
 * published READMEs, so the page stays reachable but hidden, and moves on at
 * once: by the router with script, by a refresh without.
 */
export function Moved({ to, title }: { to: string; title: string }) {
  const router = useRouter();
  useEffect(() => { void router.replace(to); }, [router, to]);
  return (
    <>
      <Head>
        <meta httpEquiv="refresh" content={`0; url=${router.basePath}${to}`} />
        <meta name="robots" content="noindex" />
      </Head>
      <p>This guide is now part of <Link href={to}>{title}</Link>.</p>
    </>
  );
}
