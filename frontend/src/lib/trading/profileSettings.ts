import type { ChartSettingsField } from './terminal'

export type ProfileKind = 'tpo' | 'session-volume-profile'

type Value = string | number | boolean
type Values = Record<string, Value>
type NumberSetting = { type: 'number'; default: number; min: number; max: number }
type BooleanSetting = { type: 'boolean'; default: boolean }
type SelectSetting<T extends string | number = string | number> = {
  type: 'select'
  default: T
  options: { label: string; value: T }[]
}
type StringSetting = { type: 'color' | 'text'; default: string }
type Setting = (NumberSetting | BooleanSetting | SelectSetting | StringSetting) & {
  label: string
  group: string
}
type SettingsOf<T extends Record<string, Setting>> = {
  [K in keyof T]: T[K] extends NumberSetting
    ? number
    : T[K] extends BooleanSetting
      ? boolean
      : T[K] extends SelectSetting<infer V>
        ? V
        : string
}

function numeric(label: string, value: number, min: number, max: number, group: string) {
  return { type: 'number' as const, label, default: value, min, max, group }
}

function boolean(label: string, value: boolean, group: string) {
  return { type: 'boolean' as const, label, default: value, group }
}

function color(label: string, value: string, group: string) {
  return { type: 'color' as const, label, default: value, group }
}

function choice<T extends string | number>(
  label: string,
  value: T,
  options: [T, string][],
  group: string
) {
  return {
    type: 'select' as const,
    label,
    default: value,
    group,
    options: options.map(([value, label]) => ({ value, label })),
  }
}

function levels(pocColor: string) {
  return {
    showPoc: boolean('POC', true, 'Profile levels'),
    pocColor: color('POC color', pocColor, 'Profile levels'),
    extendPoc: boolean('Extend POC right', false, 'Profile levels'),
    showVah: boolean('VAH', true, 'Profile levels'),
    vahColor: color('VAH color', '#8892a6', 'Profile levels'),
    extendVah: boolean('Extend VAH right', false, 'Profile levels'),
    showVal: boolean('VAL', true, 'Profile levels'),
    valColor: color('VAL color', '#8892a6', 'Profile levels'),
    extendVal: boolean('Extend VAL right', false, 'Profile levels'),
  }
}

const sessions = {
  sessionMode: choice<'all' | 'custom'>(
    'Sessions',
    'all',
    [
      ['all', 'All sessions'],
      ['custom', 'Custom hours'],
    ],
    'Sessions'
  ),
  sessionStart: {
    type: 'text',
    label: 'Session start (HH:mm)',
    default: '09:15',
    group: 'Sessions',
  },
  sessionEnd: { type: 'text', label: 'Session end (HH:mm)', default: '15:30', group: 'Sessions' },
} satisfies Record<string, Setting>

// Definitions are shared by form controls and persisted-value normalization,
// so the renderer always receives the same constraints the form advertises.
const tpo = {
  ...sessions,
  periodUnit: choice<'day' | 'week' | 'month'>(
    'Period',
    'day',
    [
      ['day', 'Day'],
      ['week', 'Week'],
      ['month', 'Month'],
    ],
    'TPO calculation'
  ),
  periodCount: numeric('Periods per profile', 1, 1, 12, 'TPO calculation'),
  blockMinutes: choice<number>(
    'Block size',
    30,
    [15, 20, 30, 45, 60, 90, 120, 180, 240].map((minutes) => [minutes, `${minutes} minutes`]),
    'TPO calculation'
  ),
  rowSizeMode: choice<'auto' | 'manual'>(
    'Row size',
    'auto',
    [
      ['auto', 'Auto'],
      ['manual', 'Manual'],
    ],
    'TPO calculation'
  ),
  ticksPerRow: numeric('Ticks per row', 20, 1, 10000, 'TPO calculation'),
  valueAreaPercent: numeric('Value area (%)', 70, 1, 100, 'TPO calculation'),
  display: choice<'letters' | 'blocks' | 'both'>(
    'Display',
    'both',
    [
      ['letters', 'Letters'],
      ['blocks', 'Blocks'],
      ['both', 'Letters and blocks'],
    ],
    'TPO appearance'
  ),
  gradientColor1: color('Gradient 1', '#2962ff', 'TPO appearance'),
  gradientColor2: color('Gradient 2', '#26a69a', 'TPO appearance'),
  gradientColor3: color('Gradient 3', '#f0a020', 'TPO appearance'),
  gradientColor4: color('Gradient 4', '#ef5350', 'TPO appearance'),
  outsideVaOpacity: numeric('Outside value area opacity (%)', 45, 0, 100, 'TPO appearance'),
  split: boolean('Split all sessions', false, 'TPO appearance'),
  ...levels('#f0a020'),
  showPoorHighLow: boolean('Poor high / low', false, 'TPO structure'),
  poorHighLowColor: color('Poor high / low color', '#ffd966', 'TPO structure'),
  showSinglePrints: boolean('Single prints', false, 'TPO structure'),
  singlePrintColor: color('Single prints color', '#e0556b', 'TPO structure'),
  showMidpoint: boolean('Midpoint', false, 'TPO structure'),
  midpointColor: color('Midpoint color', '#9c89ff', 'TPO structure'),
  showOpen: boolean('Session open', false, 'TPO structure'),
  openColor: color('Session open color', '#5ca8ff', 'TPO structure'),
  showClose: boolean('Session close', false, 'TPO structure'),
  closeColor: color('Session close color', '#ff6b5e', 'TPO structure'),
  showInitialBalance: boolean('Initial balance', true, 'TPO structure'),
  initialBalanceBlocks: numeric('Initial balance blocks', 2, 1, 12, 'TPO structure'),
  initialBalanceColor: color('Initial balance color', '#c8853a', 'TPO structure'),
  showVolumeProfile: boolean('Show volume profile', false, 'Volume overlay'),
  volumePlacement: choice<'left' | 'right'>(
    'Volume placement',
    'right',
    [
      ['left', 'Left'],
      ['right', 'Right'],
    ],
    'Volume overlay'
  ),
  volumeWidthPercent: numeric('Volume width (%)', 25, 1, 100, 'Volume overlay'),
  volumeColor: color('Volume color', '#3b5168', 'Volume overlay'),
  showVolumeValues: boolean('Volume values', false, 'Volume overlay'),
  volumeValuesColor: color('Volume values color', '#d1d5db', 'Volume overlay'),
  volumeValueAreaPercent: numeric('Volume value area (%)', 70, 1, 100, 'Volume overlay'),
  volumeVaColor: color('Volume value area color', '#4a6fa5', 'Volume overlay'),
  showVolumePoc: boolean('Volume POC', false, 'Volume overlay levels'),
  volumePocColor: color('Volume POC color', '#f0a020', 'Volume overlay levels'),
  showVolumeVah: boolean('Volume VAH', false, 'Volume overlay levels'),
  volumeVahColor: color('Volume VAH color', '#8892a6', 'Volume overlay levels'),
  showVolumeVal: boolean('Volume VAL', false, 'Volume overlay levels'),
  volumeValColor: color('Volume VAL color', '#8892a6', 'Volume overlay levels'),
} satisfies Record<string, Setting>

const svp = {
  widthPercent: numeric('Width (%)', 100, 1, 100, 'Volume appearance'),
  placement: choice<'left' | 'right'>(
    'Placement',
    'left',
    [
      ['left', 'Left'],
      ['right', 'Right'],
    ],
    'Volume appearance'
  ),
  showValues: boolean('Volume values', false, 'Volume appearance'),
  valuesColor: color('Values color', '#d1d5db', 'Volume appearance'),
  volumeMode: choice<'up-down' | 'total' | 'delta'>(
    'Volume',
    'up-down',
    [
      ['up-down', 'Up / down'],
      ['total', 'Total'],
      ['delta', 'Delta (estimated)'],
    ],
    'Volume appearance'
  ),
  upColor: color('Outside value area up', '#248fa0', 'Volume appearance'),
  downColor: color('Outside value area down', '#8e3b78', 'Volume appearance'),
  vaUpColor: color('Value area up', '#2cc5c5', 'Volume appearance'),
  vaDownColor: color('Value area down', '#ce51b0', 'Volume appearance'),
  showHistogramBox: boolean('Histogram box', false, 'Volume appearance'),
  histogramBoxColor: color('Histogram box color', '#4a6fa5', 'Volume appearance'),
  ...levels('#ffffff'),
  showDevelopingPoc: boolean('Developing POC', false, 'Profile levels'),
  showDevelopingVa: boolean('Developing value area', false, 'Profile levels'),
  rowsLayout: choice<'number-of-rows' | 'ticks-per-row'>(
    'Rows layout',
    'number-of-rows',
    [
      ['number-of-rows', 'Number of rows'],
      ['ticks-per-row', 'Ticks per row'],
    ],
    'Volume calculation'
  ),
  rowCount: numeric('Number of rows', 24, 10, 200, 'Volume calculation'),
  ticksPerRow: numeric('Ticks per row', 20, 1, 10000, 'Volume calculation'),
  valueAreaPercent: numeric('Value area (%)', 70, 1, 100, 'Volume calculation'),
  ...sessions,
} satisfies Record<string, Setting>

export type TpoProfileSettings = SettingsOf<typeof tpo> & { kind: 'tpo' }
export type SessionVolumeProfileSettings = SettingsOf<typeof svp> & {
  kind: 'session-volume-profile'
}
export type ProfileSettings = TpoProfileSettings | SessionVolumeProfileSettings

function definitions(kind: ProfileKind): Record<string, Setting> {
  return kind === 'tpo' ? tpo : svp
}

function prefix(kind: ProfileKind): string {
  return kind === 'tpo' ? 'profiles.tpo.' : 'profiles.svp.'
}

function normalize(setting: Setting, value: unknown): Value {
  if (setting.type === 'number') {
    const n =
      typeof value === 'number'
        ? value
        : typeof value === 'string' && value.trim() !== ''
          ? Number(value)
          : Number.NaN
    return Number.isFinite(n)
      ? Math.min(setting.max, Math.max(setting.min, Math.round(n)))
      : setting.default
  }
  if (setting.type === 'boolean') return typeof value === 'boolean' ? value : setting.default
  if (setting.type === 'select') {
    const selected =
      typeof setting.default === 'number' && typeof value === 'string' && value.trim() !== ''
        ? Number(value)
        : value
    return setting.options.find((option) => option.value === selected)?.value ?? setting.default
  }
  if (typeof value !== 'string') return setting.default
  const text = value.trim()
  if (setting.type === 'color') {
    if (/^#[0-9a-f]{6}$/i.test(text)) return text.toLowerCase()
    if (/^#[0-9a-f]{3}$/i.test(text)) {
      return `#${[...text.slice(1)].map((digit) => digit + digit).join('')}`.toLowerCase()
    }
    return setting.default
  }
  // Custom windows may wrap midnight. Equal start/end represents all hours.
  const time = /^(\d{1,2}):?(\d{2})$/.exec(text)
  if (!time || Number(time[1]) > 23 || Number(time[2]) > 59) return setting.default
  return `${time[1].padStart(2, '0')}:${time[2]}`
}

/** Only this type's defaults, suitable for the chart dialog's deferred reset. */
export function profileDefaults(kind: ProfileKind): Values {
  return Object.fromEntries(
    Object.entries(definitions(kind)).map(([key, setting]) => [
      `${prefix(kind)}${key}`,
      setting.default,
    ])
  )
}

/** Namespaced normalized form values; ignores unrelated chart and profile keys. */
export function profileValues(kind: ProfileKind, persisted: Record<string, unknown>): Values {
  return Object.fromEntries(
    Object.entries(definitions(kind)).map(([key, setting]) => {
      const fullKey = `${prefix(kind)}${key}`
      return [fullKey, normalize(setting, persisted[fullKey])]
    })
  )
}

export function readProfileSettings(
  kind: 'tpo',
  persisted: Record<string, unknown>
): TpoProfileSettings
export function readProfileSettings(
  kind: 'session-volume-profile',
  persisted: Record<string, unknown>
): SessionVolumeProfileSettings
export function readProfileSettings(
  kind: ProfileKind,
  persisted: Record<string, unknown>
): ProfileSettings
export function readProfileSettings(
  kind: ProfileKind,
  persisted: Record<string, unknown>
): ProfileSettings {
  return {
    kind,
    ...Object.fromEntries(
      Object.entries(definitions(kind)).map(([key, setting]) => [
        key,
        normalize(setting, persisted[`${prefix(kind)}${key}`]),
      ])
    ),
  } as ProfileSettings
}

/** Price-tab controls use the chart's existing field vocabulary and color pairs. */
export function profileFields(kind: ProfileKind): ChartSettingsField[] {
  const fields: ChartSettingsField[] = []
  const defs = definitions(kind)
  const namespace = prefix(kind)
  for (const [key, setting] of Object.entries(defs)) {
    if (key === 'downColor' || key === 'vaDownColor') continue
    if (key === 'upColor' || key === 'vaUpColor') {
      const downKey = key === 'upColor' ? 'downColor' : 'vaDownColor'
      fields.push({
        key: `${namespace}${key}Pair`,
        type: 'colorPair',
        label: key === 'upColor' ? 'Outside value area' : 'Value area',
        group: setting.group,
        up: { key: `${namespace}${key}`, label: 'Up', default: String(setting.default) },
        down: {
          key: `${namespace}${downKey}`,
          label: 'Down',
          default: String(defs[downKey].default),
        },
      })
    } else {
      fields.push({
        key: `${namespace}${key}`,
        type: setting.type,
        label: setting.label,
        group: setting.group,
        ...(setting.type === 'select'
          ? { options: setting.options.map((option) => ({ ...option })) }
          : {}),
        ...(setting.type === 'number' ? { min: setting.min, max: setting.max, step: 1 } : {}),
      })
    }
  }
  return fields
}

export function isProfileKind(kind: string): kind is ProfileKind {
  return kind === 'tpo' || kind === 'session-volume-profile'
}
