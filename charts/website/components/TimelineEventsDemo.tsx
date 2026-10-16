import RunnableExample from './RunnableExample';
import { STOCK_BARS_SOURCE } from './synthetic-market';

const code = `${STOCK_BARS_SOURCE}
el.classList.add('oac-timeline-events');
const toolbar = document.createElement('div');
toolbar.className = 'oac-timeline-events__toolbar';
const chartHost = document.createElement('div');
chartHost.className = 'oac-timeline-events__chart';
const detailHost = document.createElement('aside');
detailHost.className = 'oac-timeline-events__detail';
detailHost.setAttribute('aria-live', 'polite');
el.append(toolbar, chartHost, detailHost);

const bars = stockBars(1700000000, 110, 3600, 100, 722, 0.005, 1700);
const widget = lib.createWidget(chartHost, {
  symbol: 'SAMPLE', exchange: 'DEMO', interval: '1h',
  persist: false, topbar: false, statusline: false, rail: false, timeNavigator: false,
  eventDetails: false,
});
widget.series.setData(bars);
widget.chart.timeScale.fitContent(bars.length);
widget.chart.setEventMarkerOptions({ clustering: true, clusterRadius: 26 });
widget.chart.setEventGroups([
  { id: 'sample-feed', label: 'Sample feed' },
  { id: 'company', label: 'Company', parentId: 'sample-feed' },
  { id: 'market', label: 'Market', parentId: 'sample-feed' },
]);
widget.chart.setEvents([
  { id: 'results', time: bars[67].time, type: 'earnings', label: 'E', group: 'company',
    title: 'Sample results' },
  { id: 'call', time: bars[67].time + 75, type: 'news', label: 'N', group: 'company',
    title: 'Sample investor call' },
  { id: 'guidance', time: bars[67].time + 180, type: 'news', label: 'G', group: 'company',
    title: 'Sample guidance note' },
  { id: 'dividend', time: bars[87].time, type: 'dividend', label: 'D', group: 'market',
    title: 'Sample dividend' },
  { id: 'bulletin', time: bars[87].time + 120, type: 'news', label: 'M', group: 'market',
    title: 'Sample market bulletin' },
]);

// A host-owned detail model. The chart only supplies event IDs and timestamps.
const content = new Map([
  ['results', { summary: 'Illustrative company update, supplied by the host application.',
    sections: [
      { title: 'Highlights', rows: [['Period', 'Example quarter'], ['Revenue', 'Illustrative figure'], ['Outlook', 'Unchanged']] },
      { title: 'Context', rows: [['Feed', 'Sample company events'], ['Status', 'Simulated']] },
    ] }],
  ['call', { summary: 'A sample follow-up call attached to the same hour as the results.',
    sections: [{ title: 'Agenda', rows: [['Topic', 'Business update'], ['Format', 'Investor Q&A']] }] }],
  ['guidance', { summary: 'A separate sample note makes the clustered marker contain three selectable events.',
    sections: [{ title: 'Details', rows: [['Category', 'Company news'], ['Status', 'Illustrative']] }] }],
  ['dividend', { summary: 'A sample corporate action at a later point on the timeline.',
    sections: [{ title: 'Details', rows: [['Type', 'Dividend'], ['Status', 'Illustrative']] }] }],
  ['bulletin', { summary: 'A simulated market bulletin near the sample dividend.',
    sections: [{ title: 'Details', rows: [['Source', 'Sample market feed'], ['Status', 'Illustrative']] }] }],
]);
let activeEvents = [];
let selectedId = '';
function node(tag, className, value) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (value !== undefined) element.textContent = value;
  return element;
}
function renderDetails() {
  detailHost.replaceChildren();
  detailHost.appendChild(node('h3', 'oac-timeline-events__heading', 'Sample event details'));
  detailHost.appendChild(node('p', 'oac-timeline-events__disclaimer', 'Illustrative events; host-supplied text.'));
  if (!activeEvents.length) {
    detailHost.appendChild(node('p', 'oac-timeline-events__empty', 'Select an event badge near the time axis to inspect its details.'));
    return;
  }
  if (activeEvents.length > 1) {
    const choices = node('div', 'oac-timeline-events__choices');
    choices.setAttribute('role', 'group');
    choices.setAttribute('aria-label', 'Events in selected cluster');
    for (const event of activeEvents) {
      const choice = node('button', '', event.title || event.label);
      choice.type = 'button';
      choice.setAttribute('aria-pressed', String(event.id === selectedId));
      choice.addEventListener('click', () => { selectedId = event.id; renderDetails(); });
      choices.appendChild(choice);
    }
    detailHost.appendChild(choices);
  }
  const event = activeEvents.find(item => item.id === selectedId) || activeEvents[0];
  const details = content.get(event.id);
  const article = node('article', 'oac-timeline-events__article');
  article.appendChild(node('h4', '', event.title || event.label));
  article.appendChild(node('time', '', new Date(event.time * 1000).toLocaleString(undefined, {
    timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short',
  })));
  article.appendChild(node('p', '', details?.summary || 'No additional details supplied.'));
  for (const section of details?.sections || []) {
    const block = node('section', 'oac-timeline-events__section');
    block.appendChild(node('h5', '', section.title));
    const list = node('dl', '');
    for (const [label, value] of section.rows) {
      list.append(node('dt', '', label), node('dd', '', value));
    }
    block.appendChild(list);
    article.appendChild(block);
  }
  const link = node('a', 'oac-timeline-events__link', 'Explore the chart event API');
  link.href = 'https://github.com/marketcalls/openalgo-charts';
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  article.appendChild(link);
  detailHost.appendChild(article);
}
renderDetails();
const unsubscribe = widget.chart.on('event:click', hit => {
  activeEvents = hit.events;
  selectedId = activeEvents[0]?.id || '';
  renderDetails();
});
function toggle(label, action) {
  const button = node('button', '', label);
  button.type = 'button';
  button.addEventListener('click', action);
  toolbar.appendChild(button);
  return button;
}
let clusters = true;
const clusterButton = toggle('Clustering: on', () => {
  clusters = !clusters;
  widget.chart.setEventMarkerOptions({ clustering: clusters });
  clusterButton.textContent = 'Clustering: ' + (clusters ? 'on' : 'off');
  clusterButton.setAttribute('aria-pressed', String(clusters));
});
clusterButton.setAttribute('aria-pressed', 'true');
let companyVisible = true;
const companyButton = toggle('Company: on', () => {
  companyVisible = !companyVisible;
  widget.chart.setEventGroupVisible('company', companyVisible);
  companyButton.textContent = 'Company: ' + (companyVisible ? 'on' : 'off');
  companyButton.setAttribute('aria-pressed', String(companyVisible));
  activeEvents = []; renderDetails();
});
companyButton.setAttribute('aria-pressed', 'true');
let marketVisible = true;
const marketButton = toggle('Market: on', () => {
  marketVisible = !marketVisible;
  widget.chart.setEventGroupVisible('market', marketVisible);
  marketButton.textContent = 'Market: ' + (marketVisible ? 'on' : 'off');
  marketButton.setAttribute('aria-pressed', String(marketVisible));
  activeEvents = []; renderDetails();
});
marketButton.setAttribute('aria-pressed', 'true');
return { destroy() { unsubscribe(); widget.destroy(); } };`;

export default function TimelineEventsDemo() {
  return <RunnableExample code={code} tiers={['widget']} height={560}
    caption="Simulated stock candles and sample events. Click a count badge near the time axis, then choose a member of its cluster. The chart sends event data to a host-owned detail panel with safe text, sections, key/value facts, and a trusted link. Toggle clustering or either event group to see how the timeline changes." />;
}
