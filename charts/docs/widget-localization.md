# Widget localization and host persistence

`WidgetOptions.translate` and `AlertUiOptions.translate` accept a synchronous
`WidgetTranslator`. The same callback reaches desktop and mobile controls, menus,
dialogs, generated forms, tooltips, accessible names, status messages and toast
dismissal. `locale` continues to control status-line number formatting separately.
No translation package or backend connection is installed by the widget.

```ts
import { createWidget, type WidgetMessageKey, type WidgetTranslator } from 'openalgo-charts/widget';

const messages: Partial<Record<WidgetMessageKey, string>> = {
  'Chart settings': 'Configuracion del grafico',
  'Close': 'Cerrar',
  'Interval {code}': 'Intervalo {code}',
  'schema.settings.tab.appearance': 'Apariencia',
};
const translate: WidgetTranslator = key => messages[key];
const widget = createWidget(container, { symbol: 'BHEL', locale: 'es-ES', translate });
```

## Message contract

The callback receives `(key, fallback, values)`. `WidgetBuiltinMessage` is the
union of built-in English source messages. `WidgetMessageKey` includes those
messages and scoped `schema.*` metadata keys. `WidgetMessageValues` contains
read-only string or number parameters. `WidgetMessageParameters<Message>` infers
the required named parameters from a message template.

Return a translated template, leaving each `{parameter}` present. The widget
interpolates values exactly once after translation, so a symbol containing braces
cannot become a second template. The callback receives a frozen copy of values.
Translation text is assigned through DOM text and attribute APIs, never HTML.
Missing entries (`undefined` or `null`), whitespace-only strings, exceptions,
non-string runtime results, or templates that add/drop named parameters fall
back to English. The library supplies fallback text, not locale dictionaries or
automatic language detection. A host can choose grammatical forms using the
numeric `values.count` supplied to count messages.

`widgetText(context, key, values?)` is the same resolver used by built-in controls.
Its typed built-in overload requires parameters for messages that contain them.
Custom panels can use `widgetText(ctx, 'schema.host.save', {}, 'Save')` for their
own namespaced messages. It returns plain text; custom hosts should also render
it with text APIs. `WidgetTranslationOptions` describes the optional callback.

The translator belongs to a widget instance, including dialogs opened later and
labels refreshed after state changes. There is no global language state. Select
the translator when constructing the widget; recreate the widget to switch every
existing control to a different language. A closure can supply newer catalog
entries to later renders, but changing that closure does not refresh all controls.

## Generated metadata keys

| Surface | Key shape |
| --- | --- |
| Settings tab | `schema.settings.tab.<tabId>` |
| Settings field | `schema.settings.<fieldKey>.label` |
| Study field | `schema.indicator.<indicatorId>.<fieldKey>.label` |
| Drawing field | `schema.drawing.<toolId>.<fieldPath>.label` |
| Alert field | `schema.alert.<fieldKey>.label` |
| Form group, help and option | `schema.<scope>.group.<group>`, `schema.<scope>.<key>.tooltip`, `schema.<scope>.<key>.option.<value>` |
| Study picker name/category | `schema.indicator.<id>.name`, `schema.indicator.category.<category>` |
| Study plot selection | `schema.indicator.<id>.plot.<plotKey>` |
| Drawing tool name | `schema.drawing.<id>.name` |
| Rail group and heading | `schema.rail.<id>.title`, `schema.rail.<id>.group.<heading>` |
| Chart type, scale and magnet | `schema.chartType.<id>`, `schema.scaleMode.<mode>`, `schema.magnet.<mode>` |
| Object kind and data status | `schema.object.kind.<kind>`, `schema.dataStatus.<state>` |
| Candle condition and alert source | `schema.barCondition.<id>.title`, `schema.alert.kind.<kind>` |
| Shortcut group and row | `schema.shortcuts.group.<group>`, `schema.shortcuts.<group>.<combo>` |

Fallbacks are the descriptor's original display text. Schema IDs and option
values never change. The picker searches localized names/categories and original
indicator IDs. A form option whose label equals its value remains a literal code
(including interval tokens). `controlsFromInputs` and `controlsFromFields` accept
optional `FormTranslationOptions` with `translate` and a stable `scope`. Direct
`renderForm` callers can pass `translate` for built-in form furniture; their own
control labels are already display-ready and are not translated a second time.

## Literal boundaries

Translation changes widget-owned words, not market or user data. Symbols,
exchanges, interval codes, numeric/date values, price formats, filenames, keyboard
chords, user drawing text/level labels, alert titles/messages, search result names,
object/instance names and configured branding labels remain literal. Generated
descriptor labels listed above are explicitly translatable metadata. Engine and
provider validation/availability diagnostics remain literal inside translated
widget feedback, as do host `toast`, `status`, menu rows and unavailable reasons.
Engine canvas labels are outside this widget contract. No translator is serialized
in chart or workspace state.

## Async persistence and account changes

Use the existing `WorkspaceRepository` and `WorkspaceStorage` contracts from
`openalgo-charts/workspace` for host-owned asynchronous persistence. The repository
awaits adapter writes, rejects failures and conflicts, and preserves its mutation
queue for a later retry. Its namespace is fixed at construction: create a new
repository for another account and fence any old UI restore before applying it.
An in-flight operation keeps its original namespace. The host owns credentials,
requests, authorization and any cancellation of old account work.

`migrateWidgetWorkspace` explicitly imports a legacy widget envelope into a
validated workspace document. Invalid versions and malformed documents are
rejected before a write. Portable documents omit credentials and trading state.
The widget's `persist`/`storage` convenience API is local preference storage for one
browser (IndexedDB by default since 2.5.10, with synchronous reads over a copy in
memory); it is not an account adapter.

Regression evidence lives in `tests/workspace-repository.test.ts` (write failure,
queue recovery, account separation, conflict and private-field stripping),
`tests/workspace-documents.test.ts` (migration and validation), and
`tests/e2e/workspace-storage.spec.ts` (IndexedDB transactions). Translation coverage
lives in `tests/widget-localization.test.ts` and the corresponding browser spec.

## Trading controls

`WidgetOptions` and `ContextMenuHooks` accept `tradingCapabilities`, `tradingMode`
and `tradingLocked`. The shared `TradingCapabilitySource` can return current
account/instrument capabilities per request. Omission preserves existing order
routes; declared unsupported placement or order types are hidden. When no order
route is available, a disabled diagnostic row explains the refusal. Supply the
mode when capabilities restrict live/analyzer operation; an unknown mode cannot
satisfy that restriction.

Active chart replay locks order rows. The host's `tradingLocked` callback covers
replay selection and workspace transitions before replay starts. Order callbacks
recheck these guards, current symbol/exchange/interval and capabilities, including
menus opened before an account or replay change. Throwing guards refuse the
action. The host still owns order validation and execution through `onOrder`.
These checks do not create a separate order authority. Focused coverage is in
`tests/widget-trading-capabilities.test.ts`.
