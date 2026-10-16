/**
 * The published releases the compatibility gate holds the working tree to, and
 * a read-only way to get their files. Shared by `scripts/check-compat.mjs`
 * (declarations) and `scripts/generate-saved-documents.mjs` (saved documents).
 *
 * A release is fetched with `npm pack`, which asks the configured registry for
 * the immutable tarball and checks its integrity, then unpacked into a cache
 * outside the repository. Nothing is installed and nothing is published. The
 * cache is keyed by version, so a second run needs no network.
 */
import { execSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, readdirSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve, sep } from 'node:path';
import { gunzipSync } from 'node:zlib';

/**
 * Each release the gate compares against, and why. The previous release moves
 * with every release; the pinned one moves when OpenAlgo upgrades. The release
 * step updates this list (CONTRIBUTING.md, Compatibility gate).
 */
export const BASELINES = [
  { version: '2.5.1', why: 'the version OpenAlgo pins' },
  { version: '2.6.0', why: 'the previous release' },
];

const NAME = 'openalgo-charts';
const CACHE = process.env.OAC_COMPAT_CACHE ?? join(tmpdir(), 'openalgo-charts-compat');

/**
 * The unpacked `package/` directory of one published release, fetched on first use.
 *
 * @param {string} version an exact release version
 * @returns {string} an absolute path holding that release's package.json and dist/
 */
export function packedRelease(version) {
  if (!/^\d+\.\d+\.\d+$/.test(version)) throw new Error(`compat: "${version}" is not an exact release version`);
  const home = join(CACHE, version);
  const done = join(home, 'package');
  if (existsSync(join(home, '.complete'))) return done;

  // Unpack beside the final place and rename, so a run stopped halfway, or two
  // runs at once, never leave a half-written release that looks complete.
  const staging = join(CACHE, `.${version}-${process.pid}`);
  rmSync(staging, { recursive: true, force: true });
  mkdirSync(staging, { recursive: true });
  try {
    // The version was checked above, so the one argument built from it is safe
    // on a shell, which Windows needs to run npm.cmd.
    execSync(`npm pack ${NAME}@${version} --pack-destination "${staging}" --silent`, { stdio: ['ignore', 'pipe', 'pipe'] });
    const tgz = readdirSync(staging).find((f) => f.endsWith('.tgz'));
    if (tgz === undefined) throw new Error(`npm pack ${NAME}@${version} wrote no tarball`);
    untar(gunzipSync(readFileSync(join(staging, tgz))), staging);
    const manifest = JSON.parse(readFileSync(join(staging, 'package', 'package.json'), 'utf8'));
    if (manifest.name !== NAME || manifest.version !== version) {
      throw new Error(`npm pack returned ${manifest.name}@${manifest.version}, not ${NAME}@${version}`);
    }
    writeFileSync(join(staging, '.complete'), `${version}\n`);
    rmSync(home, { recursive: true, force: true });
    mkdirSync(dirname(home), { recursive: true });
    renameSync(staging, home);
  } catch (error) {
    rmSync(staging, { recursive: true, force: true });
    if (existsSync(join(home, '.complete'))) return done; // another run finished first
    throw new Error(`compat: cannot fetch ${NAME}@${version} (${error.message.split('\n')[0]}). `
      + 'The gate needs the registry once per version; set OAC_COMPAT_CACHE to reuse an unpacked cache.');
  }
  return done;
}

/**
 * Unpack a ustar archive, regular files only. A registry tarball has no links
 * and no device entries, and a name that would land outside `dest` is refused.
 *
 * @param {Buffer} buf the uncompressed archive
 * @param {string} dest
 */
function untar(buf, dest) {
  const root = resolve(dest);
  let offset = 0;
  let longName = null;
  while (offset + 512 <= buf.length) {
    const header = buf.subarray(offset, offset + 512);
    if (header.every((b) => b === 0)) break;
    const field = (at, length) => header.subarray(at, at + length).toString('utf8').replace(/\0[\s\S]*$/, '');
    const prefix = field(345, 155);
    let name = prefix ? `${prefix}/${field(0, 100)}` : field(0, 100);
    const size = parseInt(field(124, 12).trim() || '0', 8);
    const type = String.fromCharCode(header[156] || 0x30);
    const body = buf.subarray(offset + 512, offset + 512 + size);
    offset += 512 + Math.ceil(size / 512) * 512;
    if (type === 'x') { longName = /\d+ path=([^\n]*)\n/.exec(body.toString('utf8'))?.[1] ?? null; continue; }
    if (type === 'g') continue;
    if (longName !== null) { name = longName; longName = null; }
    if (type !== '0' && type !== '7') continue;
    const target = resolve(root, name);
    if (!target.startsWith(root + sep)) throw new Error(`tarball entry "${name}" points outside the package`);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, body);
  }
}
