/**
 * The website's Benchmarks page quotes benchmarks/releases.json. This fails
 * when the two disagree, so a hand edit to either shows up in CI.
 *
 *   node scripts/check-benchmark-page.mjs           # check, exit 1 on drift
 *   node scripts/check-benchmark-page.mjs --write   # regenerate the block
 */
import { pageWithBlock, readReleases, writePage } from './release-benchmarks.mjs';

const data = readReleases();
if (process.argv.includes('--write')) {
  console.log(writePage(data) ? 'benchmark page: block rewritten' : 'benchmark page: already current');
} else if (pageWithBlock(data).changed) {
  console.error('benchmark page: website/pages/benchmarks.mdx does not quote benchmarks/releases.json.');
  console.error('Run: node scripts/check-benchmark-page.mjs --write');
  process.exit(1);
} else {
  console.log('benchmark page: the page and benchmarks/releases.json agree');
}
