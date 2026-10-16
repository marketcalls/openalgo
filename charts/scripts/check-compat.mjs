/**
 * The compatibility gate, first half: every tier's public declarations held to
 * earlier releases (CLAUDE.md, Quality gates: Compatibility). The second half
 * is the saved-document round trip in tests/saved-documents.test.ts.
 *
 *   node scripts/check-compat.mjs [--against 2.5.1,2.5.10] [--verbose] [--json out.json]
 *   node scripts/check-compat.mjs --current 2.5.1 --against 2.5.10   # a published release in place of the build
 *
 * Runs after `build`. A minor release is additive, so for every release in
 * `BASELINES` (scripts/compat-packages.mjs) it requires:
 *
 * - every tier that release had, and every name each tier exported, is still
 *   exported, still as a value where it was one and still as a type;
 * - every member of every type reachable from those exports still exists;
 * - nothing accepts less or promises less. Which of the two a type needs
 *   depends on the direction it travels. A value the library hands to the host
 *   (a return, a property of a returned object, an argument the library passes
 *   to a host callback) may only get narrower: the new type must be assignable
 *   to the old. A value the host hands to the library (an argument, an option,
 *   a return from a host callback) may only get wider: the old type must be
 *   assignable to the new. The walk starts from each exported value as
 *   "handed back" and flips the direction at every parameter list, so options
 *   and callbacks are held the right way round at any depth. A type reached in
 *   both directions is held both ways. A type no value reaches is one a host
 *   names to read what the library gives it (an event map read through an
 *   index, a document the library parses from `unknown`), so it is held as
 *   handed back; the saved-document test covers what a host writes.
 *
 * TypeScript alone would miss three of those: it checks a method's parameters
 * both ways round (so a narrowed method argument passes), it accepts an object
 * with an optional member removed (so an option that silently stopped working
 * passes), and it compares classes by their private members (so every class
 * differs from its previous release). The walk therefore compares members and
 * signatures itself and asks the compiler only about leaves. Private members
 * are dropped from the declarations before they are read, and a member whose
 * name starts with an underscore is skipped: COMPATIBILITY.md says neither is
 * public. A class instance, and an interface in `HANDLES`, is something the
 * host only ever holds because the library made it, so it is held as handed
 * back even where the host passes it in again. A generic position is read as
 * its constraint.
 *
 * A union that gains a member on the way out (a new chart type in a returned
 * name, a new variant of a returned document) is additive, reported and not
 * failed; one that gains undefined, null, a primitive, an array or a function
 * where it had none is a narrowing. A removal or a narrowing fails unless
 * COMPATIBILITY.md lists it under Deprecated APIs with a removal release in a
 * later major.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import process from 'node:process';
import { pathToFileURL } from 'node:url';
import ts from 'typescript';
import { BASELINES, packedRelease } from './compat-packages.mjs';

const ROOT = resolve(import.meta.dirname, '..');
const PKG = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8'));

const IN = 1;
const OUT = 2;
const BOTH = 3;
const flip = (pol) => (pol === IN ? OUT : pol === OUT ? IN : BOTH);
const DIRECTION = { [IN]: 'host passes in', [OUT]: 'library hands back', [BOTH]: 'both ways' };

/** What each kind of finding means, in the words the report prints. */
export const KINDS = {
  'tier-removed': 'tier no longer exported',
  'export-removed': 'export removed',
  'no-longer-value': 'no longer a value (only a type)',
  'no-longer-type': 'no longer a type (only a value)',
  removed: 'member removed',
  'now-required': 'optional member is now required',
  'now-optional': 'member is now optional, so it may be missing',
  'new-required': 'new required member the host does not supply',
  'not-callable': 'no longer callable',
  'index-removed': 'index signature removed',
  'parameter-removed': 'parameter removed, so a call passing it no longer compiles',
  'more-arguments': 'requires more arguments than before',
  'fewer-arguments': 'callback is called with fewer arguments than it requires',
  'no-longer-accepted': 'no longer accepts',
  'may-now-return': 'may now hand back',
  narrowed: 'type changed incompatibly',
  'now-readonly': 'array handed back is now readonly',
  'now-mutable': 'array passed in must now be mutable',
  'tuple-shorter': 'tuple is shorter',
  'variant-added': 'union gained',
  'tuple-longer': 'tuple gained elements',
};
const ADDITIVE = new Set(['variant-added', 'tuple-longer']);

/**
 * Interfaces only the library implements. The host receives one from the
 * library and may pass it back, but never builds one, so a member added to it
 * is additive, the way a method added to a class is. Everything else a host
 * passes in is held to what the host could have written against the old
 * release. An entry must name a current export, or the check fails.
 */
const HANDLES = [
  // A study on the chart: `chart.addIndicator` makes it, and the drawing tier
  // asks the host for the chart's own (`indicators?(): readonly IndicatorApi[]`).
  'IndicatorApi',
];

/**
 * Names COMPATIBILITY.md lists under Deprecated APIs with a removal release in a later major.
 *
 * @param {string} text the Markdown of COMPATIBILITY.md
 * @returns {{ names: string[], removedIn: string }[]}
 */
export function deprecations(text = readFileSync(join(ROOT, 'COMPATIBILITY.md'), 'utf8')) {
  const section = text.split(/^## Deprecated APIs$/m)[1]?.split(/^## /m)[0] ?? '';
  const major = Number(PKG.version.split('.')[0]);
  const rows = [];
  for (const line of section.split('\n')) {
    const cells = line.split('|').slice(1, -1).map((c) => c.trim());
    if (cells.length < 5 || !/^\d+\.\d+\.\d+$/.test(cells[3])) continue;
    if (Number(cells[3].split('.')[0]) <= major) continue;
    rows.push({ names: [...cells[0].matchAll(/`([^`]+)`/g)].map((m) => m[1]), removedIn: cells[3] });
  }
  return rows;
}

/** A finding's subject is deprecated when a row names it whole, or names its owner and its member. */
function deprecatedBy(rows, where) {
  const path = where.replace(/\(.*$/, '').replace(/\[\]/g, '');
  const parts = path.split('.');
  return rows.find((row) => row.names.includes(path)
    || (parts.length > 1 && row.names.includes(parts[0]) && row.names.includes(parts[parts.length - 1])));
}

// Declarations -------------------------------------------------------------

const slash = (p) => p.replace(/\\/g, '/');
const fileKey = (p) => slash(p).toLowerCase();

/** A class's private members, cut out of its declaration text so the class compares by its public shape. */
function dropPrivateMembers(text, fileName) {
  const source = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true);
  const cuts = [];
  const visit = (node) => {
    if (ts.isClassDeclaration(node)) {
      for (const member of node.members) {
        const isPrivate = (member.name !== undefined && ts.isPrivateIdentifier(member.name))
          || (ts.getCombinedModifierFlags(member) & ts.ModifierFlags.Private) !== 0;
        if (isPrivate) cuts.push([member.getFullStart(), member.getEnd()]);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  let out = text;
  for (const [start, end] of cuts.reverse()) out = out.slice(0, start) + out.slice(end);
  return out;
}

/**
 * One package's tiers as virtual files under their own root, so the old and the
 * current declarations live in one program and each resolves its own
 * `openalgo-charts` imports to itself.
 */
function packageFiles(label, dir) {
  const manifest = JSON.parse(readFileSync(join(dir, 'package.json'), 'utf8'));
  const root = slash(join(ROOT, '.compat-virtual', label));
  const tiers = Object.entries(manifest.exports).map(([sub, entry]) => ({
    specifier: sub === '.' ? manifest.name : `${manifest.name}/${sub.slice(2)}`,
    file: `${root}/${entry.types.replace(/^\.\//, '')}`,
    disk: join(dir, entry.types),
  }));
  const files = new Map(tiers.map((t) => [fileKey(t.file), dropPrivateMembers(readFileSync(t.disk, 'utf8'), t.file)]));
  return { label, root, version: manifest.version, tiers, files };
}

function createProgram(packages) {
  const options = {
    strict: true, noEmit: true, skipLibCheck: true, types: [],
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler,
    lib: ['lib.es2022.d.ts', 'lib.dom.d.ts', 'lib.dom.iterable.d.ts'],
  };
  const host = ts.createCompilerHost(options, true);
  const text = (f) => { for (const p of packages) { const t = p.files.get(fileKey(f)); if (t !== undefined) return t; } return undefined; };
  const getSourceFile = host.getSourceFile.bind(host);
  const fileExists = host.fileExists.bind(host);
  const readFile = host.readFile.bind(host);
  host.getSourceFile = (f, language) => {
    const t = text(f);
    return t === undefined ? getSourceFile(f, language) : ts.createSourceFile(f, t, language, true);
  };
  host.fileExists = (f) => text(f) !== undefined || fileExists(f);
  host.readFile = (f) => text(f) ?? readFile(f);
  host.resolveModuleNameLiterals = (literals, containingFile) => literals.map((literal) => {
    const owner = packages.find((p) => fileKey(containingFile).startsWith(fileKey(p.root) + '/'));
    const tier = owner?.tiers.find((t) => t.specifier === literal.text);
    return { resolvedModule: tier && { resolvedFileName: tier.file, extension: ts.Extension.Dts, isExternalLibraryImport: false } };
  });
  return ts.createProgram(packages.flatMap((p) => p.tiers.map((t) => t.file)), options, host);
}

// The walk -----------------------------------------------------------------

/** Carried with a comparison: the member it belongs to is optional (not passed on), or the root is a constant (passed on). */
const OPTIONAL = 1;
const LOOSE = 2;

class Walk {
  /**
   * @param {ts.Program} program
   * @param {ReadonlySet<string>} handles interfaces only the library implements (see HANDLES)
   */
  constructor(program, handles) {
    this.program = program;
    this.checker = program.getTypeChecker();
    this.handles = handles;
    this.ids = new WeakMap();
    this.nextId = 1;
    this.memo = new Map();
    /** Old-side types the walk reached, with the directions it reached them in. */
    this.reached = new Map();
    /** The export the walk started from, recorded on each finding so the report can say how it was reached. */
    this.root = '';
  }

  note(out, kind, where, pol, detail) {
    out.push({ kind, where, pol, detail, via: this.root });
  }

  id(type) {
    let id = this.ids.get(type);
    if (id === undefined) { id = this.nextId++; this.ids.set(type, id); }
    return id;
  }

  show(type) {
    const text = this.checker.typeToString(type, undefined, ts.TypeFormatFlags.NoTruncation)
      .replace(/import\("[^"]*"\)\./g, '');
    return text.length > 160 ? `${text.slice(0, 157)}...` : text;
  }

  /** A generic position read as its constraint: `K extends keyof M` as `keyof M`, `M[K]` as every value of M. */
  settle(type) {
    const generic = ts.TypeFlags.TypeParameter | ts.TypeFlags.IndexedAccess | ts.TypeFlags.Conditional
      | ts.TypeFlags.Substitution | ts.TypeFlags.Index;
    for (let i = 0; i < 4 && (type.flags & generic) !== 0; i++) {
      type = this.checker.getBaseConstraintOfType(type) ?? this.checker.getAnyType();
    }
    return type;
  }

  isDefaultLib(symbol) {
    return symbol?.declarations?.some((d) => this.program.isSourceFileDefaultLibrary(d.getSourceFile())) ?? false;
  }

  /** The name a finding is filed under: the type's own when it has one, so a type reached twice reads the same. */
  nameOf(type) {
    const alias = type.aliasSymbol;
    if (alias !== undefined && !this.isDefaultLib(alias)) return alias.getName();
    const symbol = type.getSymbol();
    if (symbol === undefined || symbol.getName().startsWith('__') || this.isDefaultLib(symbol)) return null;
    const named = ts.ObjectFlags.Interface | ts.ObjectFlags.Class | ts.ObjectFlags.Reference;
    return (type.flags & ts.TypeFlags.Object) !== 0 && (type.objectFlags & named) !== 0 ? symbol.getName() : null;
  }

  isObject(type) {
    if ((type.flags & ts.TypeFlags.Object) !== 0) return true;
    return type.isIntersection() && type.types.every((t) => (t.flags & ts.TypeFlags.Object) !== 0);
  }

  /** A class instance or a handle: something the host holds because the library made it. */
  isLibraryMade(type) {
    const symbol = type.getSymbol();
    if ((type.flags & ts.TypeFlags.Object) === 0 || symbol === undefined) return false;
    if ((symbol.flags & ts.SymbolFlags.Class) !== 0 && (type.objectFlags & ts.ObjectFlags.Anonymous) === 0) return true;
    return this.handles.has(this.nameOf(type) ?? '');
  }

  /** A DOM or standard-library class or interface, compared by identity and type arguments, never member by member. */
  isLibReference(type) {
    const kinds = ts.ObjectFlags.Interface | ts.ObjectFlags.Class | ts.ObjectFlags.Reference;
    return (type.flags & ts.TypeFlags.Object) !== 0 && (type.objectFlags & kinds) !== 0 && this.isDefaultLib(type.getSymbol());
  }

  /** What makes two members of a union, or of an intersection, the same member in both releases. */
  identity(type) {
    const c = this.checker;
    if (type.flags & ts.TypeFlags.TypeParameter) return `type parameter ${type.getSymbol()?.getName()}`;
    if (type.isIntersection()) {
      // An anonymous constituent (`CanvasImageSource & { width: number }`) is paired by the named ones beside it.
      const keys = type.types.map((t) => this.identity(t) ?? '{}');
      return keys.some((k) => k !== '{}') ? keys.sort().join(' & ') : null;
    }
    if ((type.flags & ts.TypeFlags.Object) === 0) return null;
    if (c.isTupleType(type)) return 'tuple';
    if (c.isArrayType(type)) return 'array';
    const name = this.nameOf(type);
    if (name !== null) return name;
    if (this.isLibReference(type)) return `lib ${type.getSymbol().getName()}`;
    if (c.getPropertiesOfType(type).length === 0) {
      if (c.getSignaturesOfType(type, ts.SignatureKind.Call).length > 0) return 'function';
      if (c.getSignaturesOfType(type, ts.SignatureKind.Construct).length > 0) return 'constructor';
    }
    return null;
  }

  assignable(source, target) { return this.checker.isTypeAssignableTo(source, target); }

  compare(o, n, pol, where, sink, mode = 0) {
    o = this.settle(o);
    n = this.settle(n);
    this.reached.set(o, (this.reached.get(o) ?? 0) | pol);
    if (o === n) return;
    const key = `${this.id(o)}|${this.id(n)}|${pol}|${mode}`;
    const known = this.memo.get(key);
    if (known === 'busy') return; // a cycle: assume the rest of it holds, as the compiler does
    if (known !== undefined) { sink.push(...known); return; }
    this.memo.set(key, 'busy');
    const found = [];
    const name = this.nameOf(o);
    if (name !== null) where = name;
    this.compareUncached(o, n, pol, where, found, mode);
    this.memo.set(key, found);
    sink.push(...found);
  }

  compareUncached(o, n, pol, where, out, mode) {
    const c = this.checker;
    const pass = mode & LOOSE;
    // A host could not have used what a `void` function returned, so it may return anything now.
    if (pol === OUT && (o.flags & ts.TypeFlags.Void) !== 0) return;
    if (o.isUnion() || n.isUnion()) return this.compareUnion(o, n, pol, where, out, mode);
    if (c.isTupleType(o) && c.isTupleType(n)) return this.compareTuple(o, n, pol, where, out, pass);
    if (c.isArrayType(o) && c.isArrayType(n)) {
      const readonly = (t) => t.getSymbol()?.getName() === 'ReadonlyArray';
      if ((pol & OUT) && !readonly(o) && readonly(n)) this.note(out, 'now-readonly', where, OUT);
      if ((pol & IN) && readonly(o) && !readonly(n)) this.note(out, 'now-mutable', where, IN);
      return this.compare(c.getTypeArguments(o)[0], c.getTypeArguments(n)[0], pol, `${where}[]`, out, pass);
    }
    if (this.isLibReference(o) || this.isLibReference(n)) {
      if (o.getSymbol() === n.getSymbol() && (o.objectFlags & ts.ObjectFlags.Reference) && (n.objectFlags & ts.ObjectFlags.Reference)) {
        const na = c.getTypeArguments(n);
        c.getTypeArguments(o).forEach((t, i) => { if (na[i]) this.compare(t, na[i], pol, `${where}<${i}>`, out, pass); });
        return;
      }
      return this.leaf(o, n, pol, where, out, mode);
    }
    if (o.isIntersection() && n.isIntersection() && this.identity(o) !== null && this.identity(o) === this.identity(n)) {
      // The same constituents on both sides: compare each with its own, and leave
      // a shared DOM or library constituent alone rather than walking its members.
      for (const part of o.types) {
        const key = this.identity(part) ?? '{}';
        const match = n.types.find((t) => (this.identity(t) ?? '{}') === key);
        if (match !== undefined) this.compare(part, match, pol, where, out, pass);
      }
      return;
    }
    if (this.isObject(o) && this.isObject(n)) return this.compareObjects(o, n, pol, where, out, pass);
    return this.leaf(o, n, pol, where, out, mode);
  }

  leaf(o, n, pol, where, out, mode) {
    // A constant's literal type follows its value: `SAVE_DEBOUNCE_MS = 400` becoming 500 changes behaviour, not a type.
    const literal = ts.TypeFlags.StringLiteral | ts.TypeFlags.NumberLiteral | ts.TypeFlags.BooleanLiteral;
    if ((mode & LOOSE) && (o.flags & literal) && (n.flags & literal)) {
      o = this.checker.getBaseTypeOfLiteralType(o);
      n = this.checker.getBaseTypeOfLiteralType(n);
    }
    if ((pol & IN) && !this.assignable(o, n)) this.note(out, 'narrowed', where, IN, `${this.show(o)} -> ${this.show(n)}`);
    if ((pol & OUT) && (o.flags & ts.TypeFlags.Void) === 0 && !this.assignable(n, o)) {
      this.note(out, 'narrowed', where, OUT, `${this.show(o)} -> ${this.show(n)}`);
    }
  }

  compareTuple(o, n, pol, where, out, mode) {
    const oa = this.checker.getTypeArguments(o);
    const na = this.checker.getTypeArguments(n);
    oa.forEach((t, i) => { if (na[i]) this.compare(t, na[i], pol, `${where}[${i}]`, out, mode); });
    if (na.length < oa.length) this.note(out, 'tuple-shorter', where, pol, `${oa.length} -> ${na.length}`);
    if (na.length > oa.length) this.note(out, 'tuple-longer', where, pol, `${oa.length} -> ${na.length}`);
  }

  /** The member of `parts` that stands for `part`: the same type, the same literal, or the same identity and tags. */
  partner(part, parts) {
    if (parts.includes(part)) return part;
    const unit = ts.TypeFlags.Literal | ts.TypeFlags.Undefined | ts.TypeFlags.Null | ts.TypeFlags.Void
      | ts.TypeFlags.String | ts.TypeFlags.Number | ts.TypeFlags.Boolean | ts.TypeFlags.BigInt | ts.TypeFlags.ESSymbol;
    if (part.flags & unit) return parts.find((p) => (p.flags & unit) && this.assignable(p, part) && this.assignable(part, p));
    const key = this.identity(part);
    if (key === null && !this.isObject(part)) return undefined;
    const candidates = parts.filter((p) => (key === null ? this.isObject(p) && this.identity(p) === null : this.identity(p) === key));
    // Variants of one union often share an identity (`Common & { type: 'number' }`,
    // `Common & { type: 'color' }`); their literal tags tell them apart.
    const tags = this.checker.getPropertiesOfType(part)
      .map((prop) => ({ name: prop.getName(), type: this.checker.getTypeOfSymbol(prop) }))
      .filter((tag) => (tag.type.flags & ts.TypeFlags.Literal) !== 0);
    const tagOf = (p, tag) => {
      const other = this.checker.getPropertyOfType(p, tag.name);
      const t = other && this.checker.getTypeOfSymbol(other);
      if (t === undefined || (t.flags & ts.TypeFlags.Literal) === 0) return 'untagged';
      return this.assignable(t, tag.type) && this.assignable(tag.type, t) ? 'same' : 'different';
    };
    const compatible = candidates.filter((p) => tags.every((tag) => tagOf(p, tag) !== 'different'));
    const tagged = compatible.filter((p) => tags.some((tag) => tagOf(p, tag) === 'same'));
    if (tagged.length === 1) return tagged[0];
    return compatible.length === 1 && candidates.length === 1 ? compatible[0] : undefined;
  }

  compareUnion(o, n, pol, where, out, mode) {
    const absent = (t) => (mode & OPTIONAL) !== 0 && (t.flags & ts.TypeFlags.Undefined) !== 0;
    const oParts = (o.isUnion() ? o.types : [o]).filter((t) => !absent(t));
    const nParts = (n.isUnion() ? n.types : [n]).filter((t) => !absent(t));
    const pass = mode & LOOSE;
    const used = new Set();
    for (const part of oParts) {
      const match = this.partner(part, nParts);
      if (match !== undefined) { used.add(match); this.compare(part, match, pol, where, out, pass); continue; }
      if ((pol & IN) && !this.assignable(part, n)) this.note(out, 'no-longer-accepted', where, IN, this.show(part));
    }
    if ((pol & OUT) === 0) return;
    // A new literal, or a new object where the union already handed back
    // objects of that shape (a new tagged variant), is additive: code written
    // for the old members still compiles. A new undefined, null, primitive,
    // array or function is not: code that read the old members stops compiling.
    const shape = (t) => {
      if (!this.isObject(t)) return 'other';
      if (this.checker.isArrayType(t) || this.checker.isTupleType(t)) return 'array';
      return this.checker.getPropertiesOfType(t).length === 0 && this.checker.getSignaturesOfType(t, ts.SignatureKind.Call).length > 0
        ? 'function' : 'object';
    };
    const oldShapes = new Set(oParts.map(shape));
    for (const part of nParts) {
      if (used.has(part) || this.assignable(part, o)) continue;
      const additive = (part.flags & (ts.TypeFlags.Literal | ts.TypeFlags.EnumLiteral)) !== 0
        || (shape(part) !== 'other' && oldShapes.has(shape(part)));
      this.note(out, additive ? 'variant-added' : 'may-now-return', where, OUT, this.show(part));
    }
  }

  compareObjects(o, n, pol, where, out, mode) {
    const c = this.checker;
    // The host never builds a class instance or a handle: it holds one the library
    // made, so whichever way it travels, it is the library's to hand back.
    if (this.isLibraryMade(o)) pol = OUT;
    const isPublic = (name) => !name.startsWith('_') && !name.startsWith('__@');
    for (const p of c.getPropertiesOfType(o)) {
      const name = p.getName();
      if (!isPublic(name)) continue;
      const at = `${where}.${name}`;
      const q = c.getPropertyOfType(n, name);
      if (q === undefined) { this.note(out, 'removed', at, pol); continue; }
      const oOptional = (p.flags & ts.SymbolFlags.Optional) !== 0;
      const nOptional = (q.flags & ts.SymbolFlags.Optional) !== 0;
      if ((pol & IN) && oOptional && !nOptional) this.note(out, 'now-required', at, IN);
      if ((pol & OUT) && !oOptional && nOptional) this.note(out, 'now-optional', at, OUT);
      this.compare(c.getTypeOfSymbol(p), c.getTypeOfSymbol(q), pol, at, out, mode | (oOptional || nOptional ? OPTIONAL : 0));
    }
    if (pol & IN) {
      for (const q of c.getPropertiesOfType(n)) {
        if ((q.flags & ts.SymbolFlags.Optional) || !isPublic(q.getName()) || c.getPropertyOfType(o, q.getName())) continue;
        this.note(out, 'new-required', `${where}.${q.getName()}`, IN);
      }
    }
    for (const info of c.getIndexInfosOfType(o)) {
      const other = c.getIndexInfosOfType(n).find((i) => i.keyType === info.keyType);
      if (other === undefined) { this.note(out, 'index-removed', where, pol, this.show(info.keyType)); continue; }
      this.compare(info.type, other.type, pol, `${where}[${this.show(info.keyType)}]`, out, mode);
    }
    for (const kind of [ts.SignatureKind.Call, ts.SignatureKind.Construct]) {
      const os = c.getSignaturesOfType(o, kind);
      if (os.length === 0) continue;
      const ns = c.getSignaturesOfType(n, kind);
      const label = kind === ts.SignatureKind.Construct ? `new ${where}` : where;
      if (ns.length === 0) { this.note(out, 'not-callable', label, pol); continue; }
      this.compareOverloads(os, ns, pol, label, out, mode);
    }
  }

  /** Each old overload against the new one that fits it best: the one with no findings, or the fewest. */
  compareOverloads(os, ns, pol, where, out, mode) {
    os.forEach((s, i) => {
      const order = ns.length === os.length ? [ns[i], ...ns.filter((_, j) => j !== i)] : ns;
      let best;
      for (const t of order) {
        const trial = [];
        this.compareSignature(s, t, pol, where, trial, mode);
        if (best === undefined || trial.length < best.length) best = trial;
        if (trial.length === 0) break;
      }
      out.push(...best);
    });
  }

  compareSignature(s, t, pol, where, out, mode) {
    const c = this.checker;
    const shape = (sig) => {
      const params = sig.getParameters();
      const decls = params.map((p) => p.valueDeclaration);
      const last = decls[decls.length - 1];
      const rest = last !== undefined && ts.isParameter(last) && last.dotDotDotToken !== undefined;
      const required = decls.filter((d) => d && ts.isParameter(d) && !d.questionToken && !d.dotDotDotToken && !d.initializer).length;
      return { params, rest, required };
    };
    const a = shape(s);
    const b = shape(t);
    const typeAt = (sh, i) => {
      if (i < sh.params.length - (sh.rest ? 1 : 0)) return c.getTypeOfSymbol(sh.params[i]);
      if (!sh.rest) return undefined;
      const restType = c.getTypeOfSymbol(sh.params[sh.params.length - 1]);
      return c.isArrayType(restType) ? c.getTypeArguments(restType)[0] : c.getAnyType();
    };
    // The host calls what the library hands back, and the library calls what the host passes in.
    if ((pol & OUT) && b.required > a.required) this.note(out, 'more-arguments', where, OUT, `${a.required} -> ${b.required}`);
    if ((pol & IN) && a.required > b.params.length && !b.rest) this.note(out, 'fewer-arguments', where, IN, `${b.params.length} < ${a.required}`);
    const count = Math.max(a.params.length, b.params.length);
    for (let i = 0; i < count; i++) {
      const at = `${where}(${a.params[i]?.getName() ?? b.params[i]?.getName() ?? i})`;
      const ot = typeAt(a, i);
      const nt = typeAt(b, i);
      if (ot === undefined) continue; // a new trailing parameter; arity is checked above
      if (nt === undefined) {
        if (pol & OUT) this.note(out, 'parameter-removed', at, OUT);
        continue;
      }
      this.compare(ot, nt, flip(pol), at, out, mode & LOOSE);
    }
    this.compare(s.getReturnType(), t.getReturnType(), pol, `${where}()`, out, mode & LOOSE);
  }
}

// One baseline -------------------------------------------------------------

function exportsOf(checker, program, file) {
  const source = program.getSourceFile(file);
  const moduleSymbol = source && checker.getSymbolAtLocation(source);
  if (!moduleSymbol) return null;
  const map = new Map();
  for (const symbol of checker.getExportsOfModule(moduleSymbol)) {
    const decl = symbol.declarations?.[0];
    const typeOnly = decl !== undefined && ts.isExportSpecifier(decl) && (decl.isTypeOnly || decl.parent.parent.isTypeOnly);
    const target = symbol.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(symbol) : symbol;
    map.set(symbol.getName(), {
      target,
      value: !typeOnly && (target.flags & ts.SymbolFlags.Value) !== 0,
      type: (target.flags & ts.SymbolFlags.Type) !== 0,
    });
  }
  return map;
}

/** A `const` export, whose literal types follow its value rather than promise one. */
function isConstant(symbol) {
  const decl = symbol.valueDeclaration;
  return decl !== undefined && ts.isVariableDeclaration(decl) && (ts.getCombinedNodeFlags(decl) & ts.NodeFlags.Const) !== 0;
}

/**
 * Every tier of the package in `oldDir` held to the package in `newDir`.
 * Each directory holds a package.json with `exports` and the declarations it names.
 *
 * @param {string} oldDir
 * @param {string} newDir
 * @param {{ names: string[], removedIn: string }[]} rows from `deprecations()`
 */
export function comparePackages(oldDir, newDir, rows) {
  const old = packageFiles('old', oldDir);
  const current = packageFiles('new', newDir);
  const program = createProgram([old, current]);
  const walk = new Walk(program, new Set(HANDLES));
  const checker = walk.checker;
  const tiers = [];
  const findings = [];
  const typeOnly = [];
  for (const tier of old.tiers) {
    const now = current.tiers.find((t) => t.specifier === tier.specifier);
    const summary = { specifier: tier.specifier, kept: 0, added: [], findings: [] };
    tiers.push(summary);
    if (now === undefined) { summary.findings.push({ kind: 'tier-removed', where: tier.specifier, pol: OUT }); continue; }
    const before = exportsOf(checker, program, tier.file);
    const after = exportsOf(checker, program, now.file);
    if (before === null || after === null) throw new Error(`check-compat: cannot read ${before === null ? tier.file : now.file}`);
    summary.added = [...after.keys()].filter((name) => !before.has(name)).sort();
    for (const [name, o] of before) {
      const n = after.get(name);
      if (n === undefined) { summary.findings.push({ kind: 'export-removed', where: name, pol: OUT }); continue; }
      summary.kept++;
      if (o.value && !n.value) summary.findings.push({ kind: 'no-longer-value', where: name, pol: OUT });
      if (o.type && !n.type) summary.findings.push({ kind: 'no-longer-type', where: name, pol: OUT });
      walk.root = name;
      if (o.value && n.value) {
        const mode = isConstant(o.target) ? LOOSE : 0;
        walk.compare(checker.getTypeOfSymbol(o.target), checker.getTypeOfSymbol(n.target), OUT, name, summary.findings, mode);
      } else if (o.type && n.type) typeOnly.push({ summary, name, o: o.target, n: n.target });
    }
  }
  // A type only a host names: after the values, so its direction is known where one exists.
  for (const { summary, name, o, n } of typeOnly) {
    const declared = checker.getDeclaredTypeOfSymbol(o);
    walk.root = name;
    walk.compare(declared, checker.getDeclaredTypeOfSymbol(n), walk.reached.get(walk.settle(declared)) ?? OUT, name, summary.findings);
  }
  for (const summary of tiers) {
    const seen = new Set();
    summary.findings = summary.findings.filter((f) => {
      const key = `${f.kind}|${f.where}|${f.pol}|${f.detail ?? ''}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }).map((f) => {
      const row = deprecatedBy(rows, f.where);
      const status = ADDITIVE.has(f.kind) ? 'additive' : row ? 'deprecated' : 'narrowing';
      return { ...f, status, direction: DIRECTION[f.pol], removedIn: row?.removedIn };
    });
    findings.push(...summary.findings.map((f) => ({ ...f, tier: summary.specifier })));
  }
  const exported = new Set(current.tiers.flatMap((t) => [...(exportsOf(checker, program, t.file)?.keys() ?? [])]));
  const stale = HANDLES.filter((name) => !exported.has(name));
  if (stale.length > 0) throw new Error(`check-compat: HANDLES names ${stale.join(', ')}, which the package no longer exports: drop it`);
  return { tiers, findings };
}

// Main ---------------------------------------------------------------------

function main() {
  const args = process.argv.slice(2);
  const flag = (name) => { const i = args.indexOf(name); return i === -1 ? undefined : args[i + 1]; };
  const verbose = args.includes('--verbose');
  const against = flag('--against')?.split(',') ?? BASELINES.map((b) => b.version);
  const release = flag('--current');
  const started = Date.now();
  const rows = deprecations();
  const results = [];
  let failed = false;
  for (const version of against) {
    let result;
    try {
      result = { version, ...comparePackages(packedRelease(version), release ? packedRelease(release) : ROOT, rows) };
    } catch (error) {
      console.error(error.code === 'ENOENT' ? `check-compat: ${error.message}. Did the build run?` : error.message);
      process.exit(1);
    }
    results.push(result);
    const why = BASELINES.find((b) => b.version === version)?.why;
    console.log(`check-compat: ${release ?? `${PKG.version} (working tree)`} against ${version}${why ? `, ${why}` : ''}`);
    for (const tier of result.tiers) {
      const count = (status) => tier.findings.filter((f) => f.status === status).length;
      console.log(`  ${tier.specifier.padEnd(28)} ${String(tier.kept).padStart(4)} kept  ${String(tier.added.length).padStart(4)} added  `
        + `${count('additive')} widened  ${count('deprecated')} deprecated  ${count('narrowing')} narrowed or removed`);
      if (verbose && tier.added.length > 0) console.log(`      added: ${tier.added.join(', ')}`);
    }
    // A type several tiers reach is one finding, printed once.
    const printed = new Set();
    for (const f of result.findings) {
      const key = `${f.kind}|${f.where}|${f.pol}|${f.detail ?? ''}`;
      if ((f.status === 'additive' && !verbose) || printed.has(key)) continue;
      printed.add(key);
      const via = f.via && f.via !== f.where.split(/[.(]/)[0] ? `, via ${f.via}` : '';
      console.log(`  ${f.status === 'narrowing' ? 'FAIL' : f.status}: ${f.where} (${f.direction}${via}): ${KINDS[f.kind]}`
        + `${f.detail ? `: ${f.detail}` : ''}${f.removedIn ? ` [removed in ${f.removedIn}]` : ''}`);
    }
    if (result.findings.some((f) => f.status === 'narrowing')) failed = true;
  }
  const out = flag('--json');
  if (out) writeFileSync(out, `${JSON.stringify(results, null, 2)}
`);
  const seconds = ((Date.now() - started) / 1000).toFixed(1);
  if (failed) {
    console.error(`check-compat: a removal or a narrowing against ${against.join(' and ')} (${seconds}s). A minor release is additive: `
      + 'restore the name or the type, or deprecate it for the next major in COMPATIBILITY.md (Deprecated APIs).');
    process.exit(1);
  }
  console.log(`check-compat: every tier is additive against ${against.join(' and ')} (${seconds}s)`);
}

if (process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href) main();
