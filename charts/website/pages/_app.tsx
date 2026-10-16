import 'nextra-theme-docs/style.css';
import '../styles/globals.css';
import type { AppProps } from 'next/app';
import { IBM_Plex_Mono, Manrope } from 'next/font/google';

const manrope = Manrope({ subsets: ['latin'], display: 'swap', variable: '--font-manrope' });
const plexMono = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  display: 'swap',
  variable: '--font-plex-mono',
});

export default function App({ Component, pageProps }: AppProps) {
  return <div className={`${manrope.variable} ${plexMono.variable} oac-site-root`}><Component {...pageProps} /></div>;
}
