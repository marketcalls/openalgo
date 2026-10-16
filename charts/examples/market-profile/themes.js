/** Complete chart, profile and control palettes for the standalone demo. */
export function createProfileThemes(dark, light, defaults) {
  // Keep display choices such as split, density and markers out of palettes.
  const baseProfile = Object.fromEntries([
    'periodColors', 'color', 'vaColor', 'valueAreaFillColor', 'valueAreaFillOpacity',
    'pocColor', 'vahColor', 'valColor', 'ibColor', 'poorColor', 'labelColor',
    'sessionOpenColor', 'lastPriceColor', 'buyTailColor', 'sellTailColor',
    'nakedColor', 'developingPocColor', 'developingVaColor',
  ].map(key => [key, defaults[key]]));
  Object.assign(baseProfile, { fillValueArea: false, volumeColor: '#348343', countColor: '#d7dce8' });

  const make = (chart, profile, chrome, scheme = 'dark') => ({
    chart, profile: { ...baseProfile, ...profile }, chrome, scheme,
  });
  return {
    dark: make(dark, {}, {
      bg: '#0a0c11', panel: '#0f121a', elev: '#151925', 'elev-2': '#1b2030',
      bd: '#344055', 'bd-soft': '#232a3a', tx: '#d7dce8', mut: '#a6aec0', faint: '#909ab0',
      acc: '#22c1a4', 'acc-2': '#2dd4bf',
    }),
    blue: make({
      ...dark, background: '#000026', grid: '#000026', axisText: '#d8d8f0',
      axisLine: '#333356', paneSeparator: '#333356', crosshair: '#8984bf',
      crosshairLabelBackground: '#353064', upColor: '#45ddd2', wickUpColor: '#45ddd2',
      downColor: '#bd8aff', wickDownColor: '#bd8aff', lastPriceUp: '#45ddd2',
      lastPriceDown: '#bd8aff', lastPriceText: '#000026',
    }, {
      periodColors: ['#e4d4ff', '#cdb0ff', '#b696ff', '#9c8bff', '#c6a0ff', '#dbb6ff',
        '#e2ceff', '#c4b0ff', '#b0a4ff', '#acaaff', '#ccd1ff', '#e5e6ff'],
      color: '#ba9cff', vaColor: '#dabaff', volumeColor: '#00c9ed', countColor: '#f1ebff',
      fillValueArea: true, valueAreaFillColor: '#5014ed', valueAreaFillOpacity: 0.17,
      pocColor: '#ff313f', vahColor: '#d82438', valColor: '#d82438', ibColor: '#75c58c', poorColor: '#75c58c',
    }, {
      bg: '#000026', panel: '#080832', elev: '#151540', 'elev-2': '#222252',
      bd: '#494977', 'bd-soft': '#25254c', tx: '#e6e4fa', mut: '#b7b3d5', faint: '#a49fc9',
      acc: '#b899ff', 'acc-2': '#cbb3ff',
    }),
    graphite: make({
      ...dark, background: '#141619', grid: '#1e2227', axisText: '#bac3cf',
      axisLine: '#343b44', paneSeparator: '#343b44', crosshair: '#8296a8',
      crosshairLabelBackground: '#394755', upColor: '#85cfc3', wickUpColor: '#85cfc3',
      downColor: '#e9918b', wickDownColor: '#e9918b', lastPriceUp: '#85cfc3',
      lastPriceDown: '#e9918b', lastPriceText: '#141619',
    }, {
      periodColors: ['#f2f4f7', '#d9e2ee', '#bdcede', '#a5bcd0', '#8ad6e0', '#b0e3df',
        '#d9e9e4', '#c8d6ea', '#a8bedc', '#ccd2e8', '#e0dcea', '#e9e8ed'],
      color: '#abbccd', vaColor: '#e0e9f2', volumeColor: '#6c98ad', countColor: '#eef2f6',
      fillValueArea: true, valueAreaFillColor: '#71869a', valueAreaFillOpacity: 0.08,
      pocColor: '#ecc58b', vahColor: '#5f7e90', valColor: '#5f7e90', ibColor: '#99bdc4',
      poorColor: '#ecc58b', sessionOpenColor: '#80d9ed', lastPriceColor: '#ffae94',
      buyTailColor: '#a7d7ba', sellTailColor: '#e9918b', labelColor: '#c5ced8',
    }, {
      bg: '#141619', panel: '#1b1e23', elev: '#252930', 'elev-2': '#303640',
      bd: '#46505e', 'bd-soft': '#303640', tx: '#f0f2f5', mut: '#c1c7d0', faint: '#a6b0bd',
      acc: '#8ad6e0', 'acc-2': '#a5e1e7',
    }),
    emerald: make({
      ...dark, background: '#071b17', grid: '#102820', axisText: '#b1cbbc',
      axisLine: '#2a483c', paneSeparator: '#2a483c', crosshair: '#73a08a',
      crosshairLabelBackground: '#2a5442', upColor: '#70d9ae', wickUpColor: '#70d9ae',
      downColor: '#f0ac8c', wickDownColor: '#f0ac8c', lastPriceUp: '#70d9ae',
      lastPriceDown: '#f0ac8c', lastPriceText: '#071b17',
    }, {
      periodColors: ['#dcf4df', '#bfe4c2', '#99d9b1', '#77d4b5', '#a0e6d3', '#c7eee5',
        '#b5dbcc', '#e2e6b0', '#cddaa0', '#aed397', '#d0eac1', '#e5eed8'],
      color: '#93c7b0', vaColor: '#d4f2df', volumeColor: '#45ad87', countColor: '#e2f4e9',
      fillValueArea: true, valueAreaFillColor: '#49ad80', valueAreaFillOpacity: 0.09,
      pocColor: '#f3cd7e', vahColor: '#508b70', valColor: '#508b70', ibColor: '#acd39a',
      poorColor: '#f3cd7e', sessionOpenColor: '#8ecfff', lastPriceColor: '#ffa87f',
      buyTailColor: '#8ae1b4', sellTailColor: '#f0ac8c', labelColor: '#c5e0d0',
    }, {
      bg: '#071b17', panel: '#0c2420', elev: '#15312b', 'elev-2': '#204136',
      bd: '#456c5b', 'bd-soft': '#29493d', tx: '#e2f2e9', mut: '#b4d2c2', faint: '#9dbfab',
      acc: '#80dfbd', 'acc-2': '#a5e5bc',
    }),
    ivory: make({
      ...light, background: '#f6f4ee', grid: '#e9e5dc', axisText: '#485567',
      axisLine: '#c8c7bf', paneSeparator: '#c8c7bf', crosshair: '#87929b',
      crosshairLabelBackground: '#47596b', upColor: '#167260', wickUpColor: '#167260',
      downColor: '#b54436', wickDownColor: '#b54436', lastPriceUp: '#167260',
      lastPriceDown: '#b54436', lastPriceText: '#ffffff',
    }, {
      periodColors: ['#243d58', '#395477', '#275f70', '#226756', '#506331', '#765722',
        '#855134', '#87454e', '#754b71', '#65517f', '#405b85', '#356269'],
      color: '#405b72', vaColor: '#193e56', volumeColor: '#84a7bb', countColor: '#263545',
      fillValueArea: true, valueAreaFillColor: '#547e99', valueAreaFillOpacity: 0.055,
      pocColor: '#a24929', vahColor: '#8495a2', valColor: '#8495a2', ibColor: '#537552',
      poorColor: '#996318', sessionOpenColor: '#075fc0', lastPriceColor: '#b03220',
      buyTailColor: '#267954', sellTailColor: '#b54436', labelColor: '#45566b',
      nakedColor: '#637385', developingPocColor: '#334458', developingVaColor: '#657c90',
    }, {
      bg: '#f6f4ee', panel: '#edeae2', elev: '#fffefa', 'elev-2': '#e2e6e2',
      bd: '#b7bcb5', 'bd-soft': '#d1d2c9', tx: '#202934', mut: '#485667', faint: '#596578',
      acc: '#006a73', 'acc-2': '#00616a',
    }, 'light'),
  };
}
