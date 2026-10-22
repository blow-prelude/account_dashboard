/* 图形符号：单色描边，尺寸随字号；全部内联，无外部字体与图标库依赖。 */

const ICON = {
  dashboard: '<rect x="3" y="3" width="7.5" height="7.5" rx="2.2"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="2.2"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="2.2"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="2.2"/>',
  reports: '<path d="M3 20.5h18"/><rect x="4.5" y="12" width="3.6" height="6" rx="1.4"/><rect x="10.2" y="7" width="3.6" height="11" rx="1.4"/><rect x="15.9" y="3.5" width="3.6" height="14.5" rx="1.4"/>',
  import: '<path d="M12 15.5V3.5m0 0L7.2 8.3M12 3.5l4.8 4.8"/><path d="M3.8 16v2.6a2 2 0 0 0 2 2h12.4a2 2 0 0 0 2-2V16"/>',
  buffer: '<path d="M3 11.5h4.2l1.6 2.6h6.4l1.6-2.6H21"/><path d="M4.8 5.2 3 11.5v5.2a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5.2l-1.8-6.3A2 2 0 0 0 17.3 4H6.7a2 2 0 0 0-1.9 1.2Z"/>',
  archive: '<ellipse cx="12" cy="5.6" rx="8" ry="2.9"/><path d="M4 5.6v5.6c0 1.6 3.6 2.9 8 2.9s8-1.3 8-2.9V5.6"/><path d="M4 11.2v5.6c0 1.6 3.6 2.9 8 2.9s8-1.3 8-2.9v-5.6"/>',
  list: '<path d="M8.5 6h12M8.5 12h12M8.5 18h12"/><circle cx="3.6" cy="6" r="1.3"/><circle cx="3.6" cy="12" r="1.3"/><circle cx="3.6" cy="18" r="1.3"/>',
  pending: '<circle cx="12" cy="12" r="8.8"/><path d="M12 7.2v5.2l3.4 2"/>',
  rules: '<path d="M4 6.2h8.4M17.6 6.2h2.4M4 12h3.4M11.4 12h8.6M4 17.8h8.4M17.6 17.8h2.4"/><circle cx="15" cy="6.2" r="2.2"/><circle cx="9" cy="12" r="2.2"/><circle cx="15" cy="17.8" r="2.2"/>',
  tag: '<path d="M20.4 12.4 12.4 20.4a2 2 0 0 1-2.8 0l-6-6a2 2 0 0 1-.6-1.4V5.2a2 2 0 0 1 2-2h7.8a2 2 0 0 1 1.4.6l6 6a2 2 0 0 1 0 2.8Z"/><circle cx="8.2" cy="8.2" r="1.4"/>',
  pie: '<path d="M12 3.2a8.8 8.8 0 1 0 8.8 8.8H12V3.2Z"/><path d="M14.4 3.6a8.8 8.8 0 0 1 6 6H14.4V3.6Z"/>',
  shield: '<path d="M12 3 5.2 5.9v5.9c0 4.3 2.9 7.4 6.8 8.8 3.9-1.4 6.8-4.5 6.8-8.8V5.9L12 3Z"/><path d="m9.4 11.9 1.8 1.8 3.4-3.6"/>',
  gear: '<circle cx="12" cy="12" r="3.1"/><path d="M12 2.6v2.6M12 18.8v2.6M4.4 4.4l1.9 1.9M17.7 17.7l1.9 1.9M2.6 12h2.6M18.8 12h2.6M4.4 19.6l1.9-1.9M17.7 6.3l1.9-1.9"/>',
  help: '<circle cx="12" cy="12" r="8.8"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1.1.9-1.1 1.7v.3"/><circle cx="12" cy="16.9" r="0.9" fill="currentColor" stroke="none"/>',
  palette: '<circle cx="12" cy="12" r="8.8"/><circle cx="9" cy="9.2" r="1.2" fill="currentColor" stroke="none"/><circle cx="15" cy="9.2" r="1.2" fill="currentColor" stroke="none"/><circle cx="9.4" cy="14.8" r="1.2" fill="currentColor" stroke="none"/>',
  plus: '<path d="M12 5.2v13.6M5.2 12h13.6"/>',
  search: '<circle cx="10.8" cy="10.8" r="6.8"/><path d="m15.8 15.8 4 4"/>',
  upload: '<path d="M12 16.2V4.4m0 0L7.6 8.8M12 4.4l4.4 4.4"/><path d="M4.2 16.4v2.2a1.6 1.6 0 0 0 1.6 1.6h12.4a1.6 1.6 0 0 0 1.6-1.6v-2.2"/>',
  download: '<path d="M12 4.2v11.6m0 0 4.4-4.4M12 15.8l-4.4-4.4"/><path d="M4.2 16.4v2.2a1.6 1.6 0 0 0 1.6 1.6h12.4a1.6 1.6 0 0 0 1.6-1.6v-2.2"/>',
  check: '<path d="m4.8 12.6 4.6 4.6L19.2 7.4"/>',
  checkCircle: '<circle cx="12" cy="12" r="8.8"/><path d="m8.2 12.2 2.6 2.6 5-5.2"/>',
  x: '<path d="m6.4 6.4 11.2 11.2M17.6 6.4 6.4 17.6"/>',
  alert: '<path d="M12 4.2 2.8 20h18.4L12 4.2Z"/><path d="M12 10v4.2"/><circle cx="12" cy="17.3" r="0.9" fill="currentColor" stroke="none"/>',
  info: '<circle cx="12" cy="12" r="8.8"/><path d="M12 11v5.4"/><circle cx="12" cy="8" r="0.9" fill="currentColor" stroke="none"/>',
  refresh: '<path d="M20.4 11.2a8.4 8.4 0 1 0-2.2 6.6"/><path d="M20.4 4.8v6.4h-6.4"/>',
  chevronR: '<path d="m9.4 5.6 6.4 6.4-6.4 6.4"/>',
  chevronD: '<path d="m5.6 9.4 6.4 6.4 6.4-6.4"/>',
  arrowUpRight: '<path d="M7 17 17 7M9.4 7H17v7.6"/>',
  edit: '<path d="M4.4 19.6h4l10-10a2.2 2.2 0 0 0-3.1-3.1l-10 10v3.1Z"/><path d="m14.2 7.4 2.4 2.4"/>',
  trash: '<path d="M4.4 6.6h15.2M9.4 6.6V4.4h5.2v2.2M6.6 6.6l.9 12.2a1.8 1.8 0 0 0 1.8 1.6h5.4a1.8 1.8 0 0 0 1.8-1.6l.9-12.2"/>',
  lock: '<rect x="5" y="10.4" width="14" height="9.6" rx="2.4"/><path d="M8.4 10.4V7.6a3.6 3.6 0 0 1 7.2 0v2.8"/>',
  eye: '<path d="M2.6 12S6 6.4 12 6.4 21.4 12 21.4 12 18 17.6 12 17.6 2.6 12 2.6 12Z"/><circle cx="12" cy="12" r="2.8"/>',
  sparkles: '<path d="M12 3.6l1.8 4.8 4.8 1.8-4.8 1.8L12 16.8l-1.8-4.8L5.4 10.2l4.8-1.8L12 3.6Z"/><path d="M18.6 15.6l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8.8-2Z"/>',
  file: '<path d="M13.6 3.6H7.4a2 2 0 0 0-2 2v12.8a2 2 0 0 0 2 2h9.2a2 2 0 0 0 2-2V8.6l-5-5Z"/><path d="M13.4 3.8v5h5"/>',
  filter: '<path d="M3.6 5.4h16.8l-6.6 7.6v5.6l-3.6 2v-7.6L3.6 5.4Z"/>',
  clock: '<circle cx="12" cy="12" r="8.8"/><path d="M12 7.2v5.2l3.4 2"/>',
  db: '<ellipse cx="12" cy="5.6" rx="7.6" ry="2.8"/><path d="M4.4 5.6v12.8c0 1.5 3.4 2.8 7.6 2.8s7.6-1.3 7.6-2.8V5.6"/>',
  folder: '<path d="M3.6 7.4a2 2 0 0 1 2-2h3.6l2 2.4h7.2a2 2 0 0 1 2 2v8.4a2 2 0 0 1-2 2H5.6a2 2 0 0 1-2-2V7.4Z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4"/>',
};

export function icon(name, size = 16, stroke = 1.6) {
  const path = ICON[name] || '';
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="${stroke}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
}
