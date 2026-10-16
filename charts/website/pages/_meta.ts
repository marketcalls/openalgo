export default {
  index: {
    title: 'Home',
    display: 'hidden',
    theme: {
      layout: 'raw',
      sidebar: false,
      toc: false,
      breadcrumb: false,
      pagination: false,
      footer: true,
    },
  },
  docs: {
    title: 'Documentation',
    type: 'page',
  },
  examples: {
    title: 'Examples',
    type: 'page',
    theme: { layout: 'full', toc: false },
  },
  // Reached from the Examples page rather than the top bar.
  'order-flow': {
    title: 'Order flow',
    type: 'page',
    display: 'hidden',
    theme: { layout: 'full', toc: false },
  },
  benchmarks: {
    title: 'Benchmarks',
    type: 'page',
  },
  api: {
    title: 'API Reference',
    type: 'page',
    href: '/openalgo-charts/api/index.html',
    newWindow: true,
  },
};
