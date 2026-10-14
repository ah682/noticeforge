'use strict';

/* The interface renders source material as text, never as executable markup. */
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = {
  notices: [],
  record: null,
  view: 'review',
  page: 1,
  selected: null,
  textMode: false,
  zoom: 1,
  review: null,
  events: [],
  relationships: { incoming: [], outgoing: [] },
  bom: [],
  loading: false,
  request: 0,
  health: null,
  modelConfig: null,
  modelRuns: [],
  modelLoading: false,
  modelStarting: false,
  modelError: null,
  modelDecision: null,
};
let modelPollTimer;
let bomRequest = 0;
let reviewRequest = 0;
const labels = {
  last_buy: 'Last buy',
  last_delivery: 'Last delivery',
  effective_change: 'Effective change',
  sample_availability: 'Sample availability',
  acknowledgment: 'Acknowledgment',
  issue_date: 'Issue date',
  revision_date: 'Revision date',
  end_of_production: 'End of production',
  raw_identifier: 'Part identifier',
  manufacturer: 'Manufacturer',
  notice_id: 'Notice ID',
  supplier: 'Supplier',
  notice_type: 'Notice type',
  title: 'Title',
  revision: 'Revision',
  item_name: 'Item name',
  item_category: 'Item category',
  change_title: 'Change title',
  change_detail: 'Change details',
  contact_type: 'Contact type',
  company: 'Company',
  email: 'Email',
  street: 'Street',
  zip_code: 'Postal code',
  city: 'City',
  country: 'Country',
};

function h(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}
function icon(name, className = '') {
  const node = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  if (className) node.setAttribute('class', className);
  node.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', `#i-${name}`);
  node.append(use);
  return node;
}
function button(text, className, handler, iconName) {
  const node = h('button', className);
  node.type = 'button';
  if (iconName) node.append(icon(iconName));
  if (text) node.append(document.createTextNode(text));
  if (handler) node.addEventListener('click', handler);
  return node;
}
function setText(selector, value) {
  $(selector).textContent = value ?? '—';
}
function display(value, fallback = 'Not specified') {
  if (value && typeof value === 'object') return value.value ?? value.raw ?? fallback;
  return value ?? fallback;
}
function dateText(value) {
  const raw = display(value, 'Not specified');
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw))
    return new Date(`${raw}T12:00:00Z`).toLocaleDateString('en-GB', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      timeZone: 'UTC',
    });
  return raw;
}
function human(value) {
  return (
    labels[value] ||
    String(value || '')
      .replaceAll('_', ' ')
      .replace(/^./, (s) => s.toUpperCase())
  );
}
function getPath(path, obj = state.record) {
  return path.split('.').reduce((value, key) => value?.[key], obj);
}
function clearError(id) {
  $(id).hidden = true;
  $(id).textContent = '';
}
function showError(id, error) {
  $(id).hidden = false;
  $(id).textContent =
    typeof error === 'string' ? error : error.message || 'Something went wrong. Please try again.';
}
function showDialog(id) {
  const dialog = $(id);
  if (!dialog.open) dialog.showModal();
}
function toast(message, error = false) {
  const node = $('#toast');
  $('span', node).textContent = message;
  node.classList.toggle('error', error);
  node.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => {
    node.hidden = true;
  }, 4500);
}
function setBusy(node, busy, message) {
  node.disabled = busy;
  if (busy) {
    if (!node.dataset.originalText) node.dataset.originalText = node.textContent;
    node.textContent = message;
  } else if (node.dataset.originalText) {
    node.textContent = node.dataset.originalText;
    delete node.dataset.originalText;
  }
}
function statusText(status) {
  return (
    {
      supported: 'Source-supported',
      reviewed: 'Reviewed',
      accepted: 'Accepted',
      corrected: 'Corrected',
      review_required: 'Review required',
      incomplete: 'Incomplete source',
    }[status] || human(status)
  );
}
function statusChip(status, text) {
  return h('span', `status-chip ${status || ''}`, text || statusText(status));
}
function currentPart(path) {
  const match = path?.match(/^parts\.(\d+)\./);
  return match ? state.record.parts[Number(match[1])] : null;
}
function fieldLabel(path) {
  const value = getPath(path);
  if (value?.kind) return human(value.kind);
  if (/\.exceptions\.\d+$/.test(path)) return 'Part exception';
  if (/\.exclusions\.\d+$/.test(path)) return 'Excluded identifier';
  if (/\.change_categories\.\d+$/.test(path)) return 'Change category';
  if (/\.part_number$/.test(path)) return 'Suggested replacement';
  return human(path?.split('.').at(-1));
}
function criticalFields(record = state.record) {
  const result = [];
  function walk(value, path) {
    if (!value || typeof value !== 'object') return;
    if ('review_status' in value && 'value' in value && 'evidence' in value) {
      result.push({ path, value });
      return;
    }
    for (const [key, child] of Object.entries(value)) walk(child, path ? `${path}.${key}` : key);
  }
  walk(record, '');
  return result;
}
function reviewCount(record = state.record) {
  const required = new Set([
    'metadata.notice_id',
    'metadata.supplier',
    'metadata.notice_type',
    'metadata.issue_date',
  ]);
  const items = new Set();
  for (const { path, value } of criticalFields(record)) {
    const hasSourceValue = Boolean(value.value || value.raw || value.evidence?.length);
    if ((value.review_status === 'review_required' && hasSourceValue) || (required.has(path) && !value.value))
      items.add(path);
  }
  for (const finding of record.findings || [])
    if (finding.severity !== 'info')
      items.add(
        finding.field_path || `${finding.code}:${(finding.part_ids || []).join(',')}:${finding.message}`,
      );
  for (const warning of record.document.warnings || [])
    if (!record.findings.some((finding) => finding.message === warning)) items.add(`coverage:${warning}`);
  if (
    !record.document.complete &&
    !record.document.warnings.length &&
    !record.findings.some((finding) => finding.code === 'coverage')
  )
    items.add('document.coverage');
  return items.size;
}

async function request(url, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeout || 90000);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    if (!response.ok) {
      let message = `Request failed (${response.status}).`;
      try {
        const body = await response.json();
        const detail = body.detail ?? body.error ?? body.message;
        if (typeof detail === 'string') message = detail;
        else if (Array.isArray(detail))
          message = detail
            .map((item) =>
              typeof item === 'string' ? item : `${(item.loc || []).slice(1).join('.')}: ${item.msg}`,
            )
            .join(' · ');
        else if (detail) message = JSON.stringify(detail);
      } catch (_) {
        /* Preserve the HTTP error when the server did not return JSON. */
      }
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return response;
  } catch (error) {
    if (error.name === 'AbortError')
      throw new Error('The request took longer than expected. Check the local service and try again.');
    if (error instanceof TypeError)
      throw new Error(
        'The local workspace could not be reached. Check that NoticeForge is running and try again.',
      );
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}
async function api(url, options) {
  return (await request(url, options)).json();
}

async function loadWorkspace() {
  clearError('#global-error');
  $('#loading-state').hidden = false;
  try {
    const result = await api('/api/notices');
    state.notices = result.notices || [];
    renderQueue();
    renderSidebar();
    if (state.notices.length) {
      const wanted = new URLSearchParams(location.search).get('notice');
      const selected = state.notices.find((n) => n.id === wanted) || state.notices[0];
      await loadNotice(selected.id);
    } else {
      $('#loading-state').hidden = true;
      $('#empty-state').hidden = false;
    }
  } catch (error) {
    $('#loading-state').hidden = true;
    showError('#global-error', error);
    const retry = button('Try again', 'button secondary', loadWorkspace);
    $('#global-error').append(document.createTextNode(' '), retry);
  }
  api('/api/health', { timeout: 10000 })
    .then((result) => {
      state.health = result;
    })
    .catch(() => {});
}
async function refreshList() {
  const result = await api('/api/notices');
  state.notices = result.notices || [];
  renderSidebar();
  renderQueue();
}
async function loadNotice(id, suppliedRecord = null) {
  if (state.loading) return;
  const token = ++state.request;
  state.loading = true;
  clearError('#global-error');
  ++bomRequest;
  ++reviewRequest;
  setBusy($('#bom-form button[type=submit]'), false);
  setBusy($('#review-submit'), false);
  clearError('#bom-error');
  clearError('#review-error');
  if (!state.record) {
    $('#loading-state').hidden = false;
    $('#notice-content').hidden = true;
  }
  try {
    const record = suppliedRecord || (await api(`/api/notices/${encodeURIComponent(id)}`));
    if (token !== state.request) return;
    clearTimeout(modelPollTimer);
    state.modelRuns = [];
    state.modelLoading = true;
    state.modelStarting = false;
    state.modelError = null;
    state.modelDecision = null;
    state.record = record;
    state.page = record.document.pages[0]?.number || 1;
    state.selected = null;
    state.review = null;
    state.events = [];
    state.relationships = { incoming: [], outgoing: [] };
    state.bom = [];
    state.textMode = false;
    state.zoom = 1;
    $('#bom-input').value = '';
    $('#bom-tab-count').hidden = true;
    $('#history-tab-count').hidden = true;
    history.replaceState(null, '', `?notice=${encodeURIComponent(record.id)}`);
    $('#empty-state').hidden = true;
    $('#notice-content').hidden = false;
    $('#export-button').disabled = false;
    renderRecord();
    renderSidebar();
    renderQueue();
    renderBOMEmpty();
    switchView(state.view);
    const preferred =
      criticalFields(record).find(
        (item) => item.value.review_status === 'review_required' && item.value.evidence.length,
      ) ||
      criticalFields(record).find(
        (item) => item.path.startsWith('parts.') && item.value.kind && item.value.evidence.length,
      );
    if (preferred) selectEvidence(preferred.value.evidence, preferred.path);
    loadHistory();
    loadModelReview();
  } catch (error) {
    showError('#global-error', error);
  } finally {
    state.loading = false;
    $('#loading-state').hidden = true;
  }
}

function renderSidebar() {
  const list = $('#sidebar-notices');
  list.replaceChildren();
  setText('#nav-review-count', state.notices.length);
  for (const notice of state.notices.slice(0, 4)) {
    const node = button(
      '',
      `sidebar-notice ${notice.status === 'review_required' || notice.status === 'incomplete' ? 'needs-review' : ''} ${notice.id === state.record?.id ? 'selected' : ''}`,
      () => loadNotice(notice.id),
    );
    node.append(
      h('strong', '', notice.notice_id || notice.filename),
      h('small', '', notice.supplier || 'Supplier not specified'),
    );
    if (notice.id === state.record?.id) node.setAttribute('aria-current', 'true');
    list.append(node);
  }
  if (!state.notices.length) list.append(h('p', 'sidebar-loading', 'No notices imported yet.'));
}
function renderQueue() {
  const search = $('#queue-search').value.trim().toLowerCase();
  const notices = state.notices.filter((notice) =>
    [notice.notice_id, notice.supplier, notice.title, notice.filename].some((value) =>
      String(value || '')
        .toLowerCase()
        .includes(search),
    ),
  );
  const list = $('#queue-list');
  list.replaceChildren();
  for (const notice of notices) {
    const node = button('', `queue-item ${notice.id === state.record?.id ? 'selected' : ''}`, () => {
      $('#queue-dialog').close();
      loadNotice(notice.id);
    });
    node.append(h('span', 'document-type', notice.notice_type || 'PCN'));
    const copy = h('span');
    copy.append(
      h('strong', '', notice.notice_id || notice.filename),
      h(
        'small',
        '',
        `${notice.supplier || 'Supplier unknown'} · ${notice.title || notice.filename || 'Untitled notice'}`,
      ),
    );
    const info = h('span', 'queue-item-info');
    info.append(statusChip(notice.status), h('small', '', `${notice.part_count ?? 0} affected parts`));
    node.append(copy, info);
    list.append(node);
  }
  if (!notices.length) {
    const empty = h('div', 'inline-empty');
    empty.append(
      icon('search'),
      h('h4', '', search ? 'No notices found.' : 'Your queue is clear.'),
      h('p', '', search ? 'Try another notice ID or supplier.' : 'Import your first notice to get started.'),
    );
    list.append(empty);
  }
  setText(
    '#queue-total',
    `${notices.length} ${notices.length === 1 ? 'notice' : 'notices'}${search ? ` of ${state.notices.length}` : ' in your workspace'}`,
  );
}
function renderRecord() {
  const record = state.record;
  const count = reviewCount(record);
  const metadata = record.metadata;
  setText('#notice-id', display(metadata.notice_id, 'Untitled notice'));
  setText('#notice-title', display(metadata.title, record.document.filename));
  setText('#notice-type', display(metadata.notice_type, 'PCN'));
  const status = $('#notice-status');
  status.textContent = statusText(record.status);
  status.className = `status-chip ${record.status}`;
  setText('#notice-supplier', display(metadata.supplier, 'Not identified'));
  setText('#notice-part-count', `${record.parts.length} ${record.parts.length === 1 ? 'part' : 'parts'}`);
  setText('#notice-review-count', count ? `${count} to review` : 'No open items');
  $('#notice-review-count').classList.toggle('attention', count > 0);
  setText('#notice-issued', dateText(metadata.issue_date));
  setText('#notice-revision', display(metadata.revision, 'Original'));
  setText('#source-filename', record.document.filename);
  setText('#source-format', record.document.media_type === 'application/pdf' ? 'PDF' : 'TEXT');
  $('#source-download').href = `/api/notices/${encodeURIComponent(record.id)}/source`;
  $('#source-download').setAttribute('download', record.document.filename);
  setText('#record-count', record.parts.length);
  setText('#record-version', `Record v${record.version} · Compiler ${record.compiler_version}`);
  setText(
    '#provenance-label',
    record.provenance === 'synthetic'
      ? 'Owned synthetic notice · Demonstration data'
      : 'User-supplied document · Source retained locally',
  );
  setText('#history-version', `Record version ${record.version}`);
  const modeLabel = $('#mode-label');
  modeLabel.replaceChildren(
    h('span'),
    document.createTextNode(
      record.mode === 'deterministic-rules'
        ? 'Deterministic extraction'
        : record.mode === 'deterministic-rules+reviewed-model-proposals'
          ? 'Rules + reviewed proposals'
          : human(record.mode),
    ),
  );
  let toggle = $('#source-text-toggle');
  if (toggle) toggle.remove();
  if (record.document.media_type === 'application/pdf') {
    toggle = button(state.textMode ? 'View PDF' : 'View text', 'source-text-toggle', () => {
      state.textMode = !state.textMode;
      toggle.textContent = state.textMode ? 'View PDF' : 'View text';
      renderSource();
    });
    toggle.id = 'source-text-toggle';
    toggle.title = 'Switch between the PDF image and extracted text';
    $('.source-toolbar').insertBefore(toggle, $('#source-format'));
  }
  renderRecords();
  renderSource();
}

function renderRecords() {
  const record = state.record;
  const root = $('#records-content');
  root.replaceChildren();
  const count = reviewCount(record);
  const summary = h(
    'div',
    `review-summary ${record.document.complete === false ? 'incomplete' : count ? '' : 'success'}`,
  );
  summary.append(icon(record.document.complete === false || count ? 'alert' : 'check'));
  const summaryText = h('div');
  if (!record.document.complete)
    summaryText.append(
      h('h4', '', 'Source coverage is incomplete'),
      h('p', '', 'Some pages or content are missing. Review coverage before relying on this record.'),
    );
  else if (count)
    summaryText.append(
      h('h4', '', `${count} ${count === 1 ? 'item needs' : 'items need'} your review`),
      h('p', '', 'Uncertain values stay unresolved until the source supports a decision.'),
    );
  else
    summaryText.append(
      h('h4', '', 'Part relationships are source-supported'),
      h('p', '', 'Select any part or deadline to inspect its evidence and record your decision.'),
    );
  summary.append(summaryText);
  root.append(summary);
  for (const relationship of state.relationships.incoming || [])
    root.append(incomingRelationship(relationship));
  if (record.relationships.length) {
    root.append(sectionLabel('REVISION RELATIONSHIPS', `${record.relationships.length} linked`));
    record.relationships.forEach((relationship, index) => {
      const card = h('div', 'relationship-card');
      const title = h('h4');
      title.append(
        icon('link'),
        document.createTextNode(
          relationship.scope === 'subset' ? 'Partial notice supersession' : human(relationship.kind),
        ),
      );
      const text = h('p');
      text.append(document.createTextNode(`${human(relationship.kind)} `));
      text.append(
        button(display(relationship.target_notice_id), '', () =>
          selectEvidence(
            relationship.evidence.length ? relationship.evidence : relationship.target_notice_id.evidence,
            `relationships.${index}.target_notice_id`,
          ),
        ),
      );
      text.append(
        document.createTextNode(
          relationship.scope === 'subset'
            ? ' for the listed parts only. Other records remain in effect.'
            : relationship.scope === 'unknown'
              ? '. The affected scope requires review.'
              : ' for all affected records.',
        ),
      );
      card.append(title, text);
      if (relationship.parts.length) card.append(h('span', 'scope-parts', relationship.parts.join(' · ')));
      root.append(card);
    });
  }
  const groups = new Map();
  record.parts.forEach((part, index) => {
    const key = `${part.group}\u0000${display(part.manufacturer, '')}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push({ part, index });
  });
  root.append(
    sectionLabel('AFFECTED PARTS & DEADLINES', `${groups.size} ${groups.size === 1 ? 'group' : 'groups'}`),
  );
  let groupNumber = 0;
  for (const entries of groups.values()) root.append(renderGroup(entries, groupNumber++));
  if (!record.parts.length) {
    const empty = h('div', 'inline-empty');
    empty.append(
      icon('alert'),
      h('h4', '', 'No affected parts identified.'),
      h(
        'p',
        '',
        'Inspect the source and the findings below. This record does not establish that no parts are affected.',
      ),
    );
    root.append(empty);
  }
  root.append(renderMetadata());
  if (record.findings.length || record.document.warnings.length) {
    const findings = h('div', 'record-findings');
    findings.append(sectionLabel('VALIDATION NOTES'));
    const seen = new Set();
    record.findings.forEach((finding) => {
      if (seen.has(finding.message)) return;
      seen.add(finding.message);
      const item = h('div', `finding ${finding.severity}`);
      item.append(icon(finding.severity === 'info' ? 'info' : 'alert'));
      if (finding.evidence?.length)
        item.append(button(finding.message, '', () => selectEvidence(finding.evidence, finding.field_path)));
      else item.append(h('span', '', finding.message));
      findings.append(item);
    });
    record.document.warnings.forEach((warning) => {
      if (!seen.has(warning)) {
        const item = h('div', 'finding');
        item.append(icon('alert'), h('span', '', warning));
        findings.append(item);
      }
    });
    root.append(findings);
  }
  if (record.unsupported_fields.length) {
    const detail = h('details', 'unsupported-detail');
    detail.append(
      h(
        'summary',
        '',
        `${record.unsupported_fields.length} unsupported ${record.unsupported_fields.length === 1 ? 'field' : 'fields'}`,
      ),
    );
    const list = h('ul');
    record.unsupported_fields.forEach((field) => list.append(h('li', '', human(field))));
    detail.append(list);
    root.append(detail);
  }
}
function sectionLabel(title, detail = '') {
  const node = h('div', 'record-section-label');
  node.append(h('h4', '', title));
  if (detail) node.append(h('span', '', detail));
  return node;
}
function incomingRelationship(relationship) {
  const card = h('div', 'relationship-card');
  const heading = h('h4');
  heading.append(
    icon('link'),
    document.createTextNode(
      relationship.scope === 'subset'
        ? 'A later notice affects selected parts'
        : 'A later notice references this record',
    ),
  );
  card.append(heading);
  const description = h('p');
  const link = button(relationship.source_notice_id || 'Linked notice', '', () =>
    loadNotice(relationship.source_id),
  );
  link.title = 'Open the later notice';
  description.append(
    link,
    document.createTextNode(
      ` ${relationship.kind === 'cancels' ? 'cancels' : 'supersedes'} ${relationship.scope === 'subset' ? 'only the listed parts. All other original records are retained.' : relationship.scope === 'all' ? 'this notice for all affected records.' : 'this notice with an unresolved scope.'}`,
    ),
  );
  card.append(description);
  const affected = relationship.affected_parts?.length
    ? relationship.affected_parts
    : relationship.parts || [];
  if (affected.length)
    card.append(
      h(
        'span',
        'scope-parts',
        affected
          .map((item) =>
            typeof item === 'string' ? item : item.part_number || item.raw_identifier?.value || item.id,
          )
          .join(' · '),
      ),
    );
  if (relationship.unaffected_parts?.length)
    card.append(
      h(
        'p',
        '',
        `${relationship.unaffected_parts.length} original part records remain outside this revision's scope.`,
      ),
    );
  return card;
}
function renderGroup(entries, number) {
  const first = entries[0].part;
  const card = h('article', 'part-group');
  const header = h('div', 'group-header');
  const title = h('div', 'group-title');
  title.append(
    h('span', 'group-marker', String.fromCharCode(65 + (number % 26))),
    document.createTextNode(
      first.group && first.group !== 'default' ? first.group : `Part group ${number + 1}`,
    ),
  );
  header.append(
    title,
    h('span', 'group-subtitle', `${entries.length} ${entries.length === 1 ? 'part' : 'parts'}`),
  );
  card.append(header);
  const chips = h('div', 'part-chips');
  entries.forEach(({ part, index }) => {
    const path = `parts.${index}.raw_identifier`;
    const chip = button(
      display(part.raw_identifier),
      `part-chip ${part.raw_identifier.review_status === 'review_required' ? 'has-review' : ''}`,
      () => selectEvidence(part.raw_identifier.evidence, path),
    );
    chip.dataset.field = path;
    chip.title = `Inspect source for ${display(part.raw_identifier)}`;
    chips.append(chip);
  });
  card.append(chips);
  const dateGroups = new Map();
  entries.forEach((entry) => {
    const key = JSON.stringify(
      entry.part.dates.map((date) => [date.kind, date.value, date.raw, date.qualifier, date.review_status]),
    );
    if (!dateGroups.has(key)) dateGroups.set(key, []);
    dateGroups.get(key).push(entry);
  });
  for (const subset of dateGroups.values()) {
    if (dateGroups.size > 1)
      card.append(
        h(
          'div',
          'subrecord-label',
          `APPLIES TO ${subset.map((entry) => display(entry.part.raw_identifier)).join(', ')}`,
        ),
      );
    const deadlines = h('div', 'group-deadlines');
    subset[0].part.dates.forEach((date, dateIndex) => {
      const path = `parts.${subset[0].index}.dates.${dateIndex}`;
      const paths = subset.map((entry) => `parts.${entry.index}.dates.${dateIndex}`);
      const row = h('div', 'deadline-row');
      row.append(icon('calendar', 'deadline-icon'), h('span', 'deadline-label', human(date.kind)));
      const value = button(
        dateText(date),
        `deadline-value ${date.review_status === 'review_required' || date.qualifier !== 'exact' ? 'uncertain' : ''}`,
        () => selectEvidence(date.evidence, path),
      );
      value.dataset.field = path;
      value.title =
        date.qualifier !== 'exact'
          ? `${human(date.qualifier)} · ${date.reason || 'Inspect source evidence'}`
          : 'Inspect source evidence';
      row.append(value);
      if (date.evidence.length) row.append(evidenceButton(date.evidence, path));
      const review = button(
        date.review_status === 'accepted' || date.review_status === 'corrected'
          ? statusText(date.review_status)
          : 'Review',
        `review-trigger ${['accepted', 'corrected'].includes(date.review_status) ? 'done' : ''}`,
        () => openReview(path, paths),
      );
      review.title = `Review ${human(date.kind).toLowerCase()}${paths.length > 1 ? ' for an individual part' : ''}`;
      row.append(review);
      deadlines.append(row);
    });
    if (!subset[0].part.dates.length) {
      const empty = h('div', 'deadline-row');
      empty.append(
        icon('alert', 'deadline-icon'),
        h('span', 'deadline-label', 'No supported part-specific deadlines'),
      );
      deadlines.append(empty);
    }
    card.append(deadlines);
  }
  entries.forEach(({ part, index }) => {
    part.exceptions.forEach((exception, exceptionIndex) => {
      const path = `parts.${index}.exceptions.${exceptionIndex}`;
      const note = h('div', 'exception');
      note.append(icon('info'));
      const copy = h('div');
      copy.append(
        h('strong', '', `${display(part.raw_identifier)} only`),
        button(display(exception), '', () => selectEvidence(exception.evidence, path)),
      );
      note.append(copy);
      if (exception.evidence.length) note.append(evidenceButton(exception.evidence, path));
      card.append(note);
    });
    part.exclusions.forEach((exclusion, exclusionIndex) => {
      const note = h('div', 'exception');
      note.append(icon('info'));
      const copy = h('div');
      copy.append(
        h('strong', '', `Exclusion · ${display(part.raw_identifier)}`),
        button(display(exclusion), '', () =>
          selectEvidence(exclusion.evidence, `parts.${index}.exclusions.${exclusionIndex}`),
        ),
      );
      note.append(copy);
      card.append(note);
    });
    part.replacement_suggestions.forEach((replacement, replacementIndex) => {
      const node = h('div', 'replacement');
      node.append(h('strong', '', `Suggested for ${display(part.raw_identifier)}: `));
      const suggestion = button(display(replacement.part_number), 'part-chip', () =>
        selectEvidence(
          replacement.part_number.evidence,
          `parts.${index}.replacement_suggestions.${replacementIndex}.part_number`,
        ),
      );
      node.append(suggestion, h('small', '', 'Supplier suggestion · Compatibility not assessed'));
      card.append(node);
    });
  });
  const footer = h('div', 'group-footer');
  const footerText = h('span', 'group-footer-text');
  footerText.append(
    icon('shield'),
    document.createTextNode(display(first.manufacturer, 'Manufacturer not specified')),
  );
  const groupReview = entries.some((entry) => entry.part.review_status === 'review_required');
  footer.append(
    footerText,
    statusChip(groupReview ? 'review_required' : 'supported', groupReview ? 'Needs review' : 'Source linked'),
  );
  card.append(footer);
  return card;
}
function evidenceButton(evidence, path) {
  const btn = button(`p.${evidence[0].page}`, 'evidence-link', () => selectEvidence(evidence, path), 'link');
  btn.title = `View evidence on page ${evidence[0].page}`;
  return btn;
}
function renderMetadata() {
  const details = h('details', 'metadata-details');
  details.append(h('summary', '', 'Notice metadata & source fields'));
  const rows = h('div', 'metadata-fields');
  const fields = [
    'notice_id',
    'supplier',
    'notice_type',
    'title',
    'issue_date',
    'revision',
    'revision_date',
    'change_title',
    'change_detail',
  ];
  for (const field of fields) {
    const value = state.record.metadata[field];
    if (
      !value ||
      (['change_title', 'change_detail', 'revision_date'].includes(field) &&
        !value.value &&
        !value.raw &&
        value.review_status !== 'review_required')
    )
      continue;
    rows.append(metadataRow(`metadata.${field}`, value, human(field)));
  }
  for (const [field, value] of Object.entries(state.record.metadata.contact || {}))
    if (value.value || value.raw)
      rows.append(metadataRow(`metadata.contact.${field}`, value, `Contact ${human(field).toLowerCase()}`));
  state.record.parts.forEach((part, index) => {
    if (part.item_name?.value)
      rows.append(metadataRow(`parts.${index}.item_name`, part.item_name, display(part.raw_identifier)));
    if (part.change_categories?.length)
      part.change_categories.forEach((value, categoryIndex) =>
        rows.append(
          metadataRow(`parts.${index}.change_categories.${categoryIndex}`, value, 'Change category'),
        ),
      );
  });
  details.append(rows);
  return details;
}
function metadataRow(path, field, label) {
  const row = h('div', 'metadata-row');
  row.append(h('span', '', label));
  const value = button(field.kind ? dateText(field) : display(field), 'metadata-value', () =>
    selectEvidence(field.evidence, path),
  );
  value.dataset.field = path;
  row.append(
    value,
    button(
      ['accepted', 'corrected'].includes(field.review_status) ? statusText(field.review_status) : 'Review',
      `review-trigger ${['accepted', 'corrected'].includes(field.review_status) ? 'done' : ''}`,
      () => openReview(path),
    ),
  );
  return row;
}

function selectEvidence(evidence = [], path = null) {
  state.selected = { evidence, path };
  if (evidence[0]) state.page = evidence[0].page;
  $$('[data-field]').forEach((node) => node.classList.toggle('selected', node.dataset.field === path));
  if (
    state.record.document.media_type === 'application/pdf' &&
    evidence.length &&
    !evidence.some((item) => item.bbox)
  ) {
    state.textMode = true;
    const toggle = $('#source-text-toggle');
    if (toggle) toggle.textContent = 'View PDF';
  }
  renderSource();
  const label = path ? fieldLabel(path) : 'Selected evidence';
  const part = currentPart(path);
  setText(
    '#evidence-caption-text',
    evidence.length
      ? `${label}${part ? ` · ${display(part.raw_identifier)}` : ''} · page ${evidence[0].page}`
      : `${label} · No source evidence available`,
  );
  $('#evidence-caption').classList.toggle('active', evidence.length > 0);
  $('#selected-review').hidden = !path || !getPath(path)?.review_status;
  requestAnimationFrame(() => {
    const selected = $('.source-mark,.pdf-highlight', $('#source-paper'));
    if (selected) {
      const canvas = $('#source-canvas');
      const offset =
        selected.getBoundingClientRect().top - canvas.getBoundingClientRect().top + canvas.scrollTop;
      canvas.scrollTo({ top: Math.max(0, offset - canvas.clientHeight * 0.32), behavior: 'smooth' });
    }
  });
}
function renderSource() {
  const record = state.record;
  if (!record) return;
  const pages = record.document.pages;
  const page = pages.find((item) => item.number === state.page) || pages[0];
  const paper = $('#source-paper');
  paper.replaceChildren();
  paper.className = 'source-paper';
  const pdfVisible = record.document.media_type === 'application/pdf' && !state.textMode;
  $('#source-zoom').hidden = !pdfVisible;
  paper.style.width = pdfVisible && state.zoom > 1 ? `${state.zoom * 100}%` : '';
  $('#zoom-out').disabled = state.zoom <= 1;
  $('#zoom-in').disabled = state.zoom >= 2.5;
  setText('#zoom-fit', state.zoom === 1 ? 'Fit' : `${Math.round(state.zoom * 100)}%`);
  if (!page) {
    paper.append(
      h(
        'p',
        'source-no-evidence',
        'No source pages are available for this notice. Import a complete source to establish coverage.',
      ),
    );
    setText('#page-indicator', 'No pages');
    $('#page-prev').disabled = true;
    $('#page-next').disabled = true;
    return;
  }
  state.page = page.number;
  const pageIndex = pages.indexOf(page);
  setText('#page-indicator', `Page ${page.number} of ${record.document.expected_pages || pages.length}`);
  $('#page-prev').disabled = pageIndex === 0;
  $('#page-next').disabled = pageIndex === pages.length - 1;
  setText('#source-method', page.method === 'text' ? 'Original text' : human(page.method));
  const evidence = (state.selected?.evidence || []).filter((item) => item.page === page.number);
  if (record.document.media_type === 'application/pdf' && !state.textMode) {
    paper.classList.add('pdf-paper');
    const image = h('img');
    image.src = `/api/notices/${encodeURIComponent(record.id)}/pages/${page.number}/image`;
    image.alt = `Original notice, page ${page.number}`;
    image.loading = 'eager';
    image.addEventListener('error', () => {
      paper.replaceChildren();
      paper.classList.remove('pdf-paper');
      paper.append(
        h('p', 'source-pdf-fallback', 'The page preview is unavailable. Extracted text is shown below.'),
      );
      renderSourceText(paper, page, evidence);
    });
    paper.append(image);
    if (page.width && page.height)
      for (const item of evidence)
        if (Array.isArray(item.bbox) && item.bbox.length === 4) {
          const [left, top, right, bottom] = item.bbox;
          const mark = h('div', 'pdf-highlight');
          mark.style.left = `${Math.max(0, (left / page.width) * 100)}%`;
          mark.style.top = `${Math.max(0, (top / page.height) * 100)}%`;
          mark.style.width = `${Math.max(0, ((right - left) / page.width) * 100)}%`;
          mark.style.height = `${Math.max(0, ((bottom - top) / page.height) * 100)}%`;
          mark.title = item.quote;
          paper.append(mark);
        }
  } else renderSourceText(paper, page, evidence);
}
function renderSourceText(paper, page, evidence) {
  paper.append(
    h(
      'div',
      'source-document-label',
      state.record.document.media_type === 'application/pdf'
        ? `EXTRACTED TEXT · PAGE ${page.number}`
        : `ORIGINAL TEXT · PAGE ${page.number}`,
    ),
  );
  const pre = h('pre', 'source-lines');
  const characters = Array.from(page.text);
  const ranges = evidence
    .map((item) => [Math.max(0, item.start), Math.min(characters.length, item.end)])
    .filter(([start, end]) => end > start)
    .sort((a, b) => a[0] - b[0]);
  const merged = [];
  for (const range of ranges) {
    const last = merged.at(-1);
    if (last && range[0] <= last[1]) last[1] = Math.max(last[1], range[1]);
    else merged.push(range);
  }
  let offset = 0;
  let firstContent = true;
  for (const line of page.text.split('\n')) {
    const length = Array.from(line).length;
    const row = h(
      'span',
      `source-line ${!line.trim() ? 'blank' : firstContent ? 'heading' : /^[A-Z][A-Z \d/_&-]{4,}:?$/.test(line.trim()) ? 'section' : ''}`,
    );
    if (line.trim()) firstContent = false;
    let cursor = offset;
    for (const [start, end] of merged) {
      const a = Math.max(start, offset);
      const b = Math.min(end, offset + length);
      if (b <= a) continue;
      if (a > cursor) row.append(document.createTextNode(characters.slice(cursor, a).join('')));
      row.append(h('mark', 'source-mark', characters.slice(a, b).join('')));
      cursor = b;
    }
    if (cursor < offset + length)
      row.append(document.createTextNode(characters.slice(cursor, offset + length).join('')));
    if (!length) row.append(document.createTextNode(' '));
    pre.append(row);
    offset += length + 1;
  }
  paper.append(pre);
  const footer = h('div', 'source-foot');
  footer.append(h('span', '', state.record.document.filename), h('span', '', `PAGE ${page.number}`));
  paper.append(footer);
}
function changePage(delta) {
  if (!state.record) return;
  const pages = state.record.document.pages;
  const index = pages.findIndex((page) => page.number === state.page);
  if (!pages[index + delta]) return;
  state.page = pages[index + delta].number;
  renderSource();
  $('#source-canvas').scrollTop = 0;
}
function zoomSource(delta) {
  state.zoom = delta === 0 ? 1 : Math.min(2.5, Math.max(1, state.zoom + delta));
  renderSource();
  if (state.zoom === 1) $('#source-canvas').scrollLeft = 0;
}

function openReview(path, paths = [path]) {
  const field = getPath(path);
  if (!field || !('value' in field)) return;
  ++reviewRequest;
  setBusy($('#review-submit'), false);
  state.review = { path, paths };
  clearError('#review-error');
  $('input[name=action][value=accept]').checked = true;
  $('#correction-field').hidden = true;
  $('#corrected-value').required = false;
  $('#review-reason').value = '';
  $('#reviewer-name').value = localStorage.getItem('noticeforge-reviewer') || '';
  $('#review-form .review-part-choice')?.remove();
  $('#review-form .review-scope')?.remove();
  if (paths.length > 1) {
    const selector = h('div', 'review-part-choice');
    const label = h('label', '', 'Review for this part');
    label.htmlFor = 'review-part-select';
    const select = h('select');
    select.id = 'review-part-select';
    paths.forEach((item) => {
      const option = h('option', '', display(currentPart(item)?.raw_identifier));
      option.value = item;
      select.append(option);
    });
    select.value = path;
    select.addEventListener('change', () => {
      state.review.path = select.value;
      populateReviewField(select.value);
    });
    selector.append(label, select);
    $('#review-form').prepend(selector);
    const scope = h(
      'p',
      'review-scope',
      'This decision applies to the selected part only. Other part relationships keep their own review status.',
    );
    selector.after(scope);
  } else if (currentPart(path)) {
    const scope = h('p', 'review-scope', `Applies to ${display(currentPart(path).raw_identifier)} only.`);
    $('#review-form').prepend(scope);
  }
  populateReviewField(path);
  selectEvidence(field.evidence, path);
  showDialog('#review-dialog');
}
function populateReviewField(path) {
  const field = getPath(path);
  setText('#review-dialog-title', `Review ${fieldLabel(path).toLowerCase()}`);
  setText('#review-original-value', display(field));
  setText(
    '#review-original-reason',
    field.reason || `${statusText(field.review_status)} · ${human(field.method || 'rules')}`,
  );
  const source = field.evidence?.map((item) => `Page ${item.page} · “${item.quote}”`).join('\n\n');
  setText(
    '#review-evidence',
    source ||
      'No source evidence is linked to this field. Do not confirm an unsupported value without a source.',
  );
  $('#corrected-value').value = field.value ?? field.raw ?? '';
  $('#corrected-value').placeholder = field.kind ? 'YYYY-MM-DD (exact date)' : 'Corrected source value';
  $('#correction-evidence')?.remove();
  const evidence = h('details', 'correction-evidence');
  evidence.id = 'correction-evidence';
  evidence.append(h('summary', '', 'Source evidence for this correction'));
  const pageLabel = h('label', '', 'Source page');
  pageLabel.htmlFor = 'correction-page';
  const select = h('select');
  select.id = 'correction-page';
  state.record.document.pages.forEach((page) => {
    const option = h('option', '', `Page ${page.number}`);
    option.value = String(page.number);
    select.append(option);
  });
  select.value = String(field.evidence?.[0]?.page || state.page);
  const quoteLabel = h('label', '', 'Exact supporting source text');
  quoteLabel.htmlFor = 'correction-quote';
  const quote = h('textarea');
  quote.id = 'correction-quote';
  quote.rows = 3;
  quote.value = field.evidence?.[0]?.quote || '';
  quote.placeholder = 'Copy an exact excerpt from the source notice';
  evidence.append(
    pageLabel,
    select,
    quoteLabel,
    quote,
    h(
      'p',
      'field-help',
      'Keep the existing excerpt if it supports the correction, or paste a more precise source excerpt. The text must occur exactly once on the selected page.',
    ),
  );
  if (!field.evidence?.length) evidence.open = true;
  $('#correction-field').append(evidence);
}
async function submitReview(event) {
  event.preventDefault();
  if (!state.review) return;
  clearError('#review-error');
  const submit = $('#review-submit');
  setBusy(submit, true, 'Saving decision…');
  const review = state.review;
  const path = review.path;
  const recordId = state.record.id;
  const workspaceRequest = state.request;
  const token = ++reviewRequest;
  const currentContext = () =>
    token === reviewRequest &&
    workspaceRequest === state.request &&
    state.record?.id === recordId &&
    state.review === review &&
    review.path === path;
  const action = $('input[name=action]:checked').value;
  const body = {
    field_path: state.review.path,
    action,
    reason: $('#review-reason').value.trim(),
    reviewer: $('#reviewer-name').value.trim(),
    expected_version: state.record.version,
  };
  try {
    if (action === 'correct') {
      body.value = $('#corrected-value').value.trim();
      const page = state.record.document.pages.find(
        (item) => item.number === Number($('#correction-page').value),
      );
      const quote = $('#correction-quote').value;
      if (!quote.trim()) {
        $('#correction-evidence').open = true;
        throw new Error('Add the exact source text that supports this correction.');
      }
      const start = page?.text.indexOf(quote) ?? -1;
      if (start < 0) {
        $('#correction-evidence').open = true;
        throw new Error(
          'The supporting excerpt does not occur on this page. Copy it exactly from the extracted source text.',
        );
      }
      if (page.text.indexOf(quote, start + 1) !== -1) {
        $('#correction-evidence').open = true;
        throw new Error(
          'This excerpt occurs more than once on the selected page. Include surrounding text to identify the intended source.',
        );
      }
      const unicodeStart = Array.from(page.text.slice(0, start)).length;
      body.evidence = {
        page: page.number,
        start: unicodeStart,
        end: unicodeStart + Array.from(quote).length,
      };
    }
    const updated = await api(`/api/notices/${encodeURIComponent(recordId)}/reviews`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    localStorage.setItem('noticeforge-reviewer', body.reviewer);
    if (!currentContext()) return;
    state.record = updated;
    $('#review-dialog').close();
    renderRecord();
    selectEvidence(getPath(path)?.evidence || [], path);
    await Promise.allSettled([refreshList(), loadHistory()]);
    if (currentContext())
      toast(
        action === 'correct'
          ? 'Correction saved with the original value in history.'
          : 'Review decision saved.',
      );
  } catch (error) {
    if (currentContext() && $('#review-dialog').open)
      showError(
        '#review-error',
        error.status === 409
          ? `${error.message} Close this dialog and reload the notice before making a new decision.`
          : error,
      );
  } finally {
    if (token === reviewRequest) setBusy(submit, false);
  }
}

function switchView(view) {
  state.view = view;
  const titles = {
    review: ['Notice review', 'Every affected part. Every deadline. Backed by evidence.'],
    model: ['Model review', 'Optional proposals. Source evidence. Your decision to apply.'],
    bom: ['BOM matching', 'Connect a supplier notice to your component inventory.'],
    history: ['Decision history', 'A clear trail from source evidence to reviewed records.'],
  };
  const [title, description] = titles[view];
  $('#page-title').replaceChildren(document.createTextNode(title), h('span', 'title-dot', '.'));
  setText('#page-description', description);
  setText('#breadcrumb-current', title);
  document.title = `NoticeForge · ${title}`;
  $$('[data-view]').forEach((node) => {
    const active = node.dataset.view === view;
    node.classList.toggle('active', active);
    if (node.getAttribute('role') === 'tab') {
      node.setAttribute('aria-selected', String(active));
      node.tabIndex = active ? 0 : -1;
    } else if (active) node.setAttribute('aria-current', 'page');
    else node.removeAttribute('aria-current');
  });
  for (const name of ['review', 'bom', 'history'])
    $(`#${name}-view`).hidden = name === 'review' ? !['review', 'model'].includes(view) : view !== name;
  $('#records-content').hidden = view === 'model';
  $('#model-content').hidden = view !== 'model';
  setText('#records-panel-title', view === 'model' ? 'Model proposals' : 'Extracted records');
  $('#records-panel-key').replaceChildren(
    h('span'),
    document.createTextNode(view === 'model' ? 'Human decision required' : 'Evidence linked'),
  );
  setText(
    '#record-count',
    view === 'model'
      ? state.modelRuns.reduce((count, run) => count + (run.result?.candidates?.length || 0), 0)
      : state.record?.parts.length || 0,
  );
  if (view === 'model') renderModelReview();
}
async function loadHistory() {
  if (!state.record) return;
  const recordId = state.record.id;
  const root = $('#history-content');
  root.replaceChildren(h('p', 'subtle', 'Loading decision history…'));
  try {
    const [audit, relationships] = await Promise.allSettled([
      api(`/api/notices/${encodeURIComponent(recordId)}/audit`),
      api(`/api/notices/${encodeURIComponent(recordId)}/history`),
    ]);
    if (state.record.id !== recordId) return;
    if (audit.status === 'rejected') throw audit.reason;
    state.events = audit.value.events || [];
    if (relationships.status === 'fulfilled') {
      state.relationships = relationships.value;
      renderRecords();
      if (state.selected?.path)
        $$('[data-field]').forEach((node) =>
          node.classList.toggle('selected', node.dataset.field === state.selected.path),
        );
    }
    renderHistory();
    const decisions = state.events.filter(
      (event) =>
        ['accept', 'correct', 'model_accept', 'model_reject'].includes(event.action) || event.field_path,
    ).length;
    $('#history-tab-count').hidden = !decisions;
    setText('#history-tab-count', decisions);
  } catch (error) {
    root.replaceChildren(h('p', 'form-error', error.message));
    root.append(button('Retry history', 'button secondary', loadHistory));
  }
}
function renderHistory() {
  const root = $('#history-content');
  root.replaceChildren();
  for (const relationship of state.relationships.incoming || [])
    root.append(incomingRelationship(relationship));
  if (!state.events.length) {
    const empty = h('div', 'inline-empty');
    empty.append(
      icon('history'),
      h('h4', '', 'The next decision starts the trail.'),
      h('p', '', 'Review a field in the evidence workspace to record your first decision.'),
    );
    root.append(empty);
    return;
  }
  for (const event of state.events) {
    const action = event.action || event.event_type || event.type || 'import';
    const card = h('article', 'history-event');
    const marker = h('span', 'history-event-icon');
    marker.append(
      icon(action === 'correct' ? 'edit' : ['accept', 'model_accept'].includes(action) ? 'check' : 'file'),
    );
    const content = h('div', 'history-event-content');
    const heading = h('div', 'history-event-heading');
    const titles = {
      correct: 'Field corrected',
      accept: 'Source value accepted',
      model_requested: 'Model review requested',
      model_completed: 'Model review completed',
      model_accept: 'Model proposal applied',
      model_reject: 'Model proposal rejected',
    };
    heading.append(h('h4', '', titles[action] || human(action)));
    const time = h('time');
    const timestamp = event.created_at || event.timestamp || event.at;
    if (timestamp) {
      const parsed = new Date(timestamp);
      time.textContent = Number.isNaN(parsed.valueOf())
        ? timestamp
        : parsed.toLocaleString('en-GB', {
            day: 'numeric',
            month: 'short',
            hour: '2-digit',
            minute: '2-digit',
          });
      time.dateTime = timestamp;
    }
    heading.append(time);
    content.append(heading);
    if (event.field_path) content.append(h('div', 'history-event-path', event.field_path));
    const oldValue = event.old_value ?? event.before ?? event.original_value;
    const newValue = event.new_value ?? event.after ?? event.value;
    if (action.startsWith('model_')) content.append(modelAuditValue(event));
    else if (oldValue !== undefined || newValue !== undefined) {
      const change = h('div', 'history-value-change');
      if (action === 'correct')
        change.append(h('del', '', display(oldValue, 'Not specified')), icon('chevron-right'));
      change.append(h('span', '', display(newValue ?? oldValue, 'Not specified')));
      content.append(change);
    }
    if (event.reason || event.message) content.append(h('p', '', event.reason || event.message));
    const author = event.reviewer || event.actor || 'Local compiler';
    const version = event.version ?? event.record_version;
    content.append(h('div', 'history-event-author', `${author}${version ? ` · Record v${version}` : ''}`));
    card.append(marker, content);
    root.append(card);
  }
}

function modelAuditValue(event) {
  const change = h('div', 'history-value-change');
  if (event.action === 'model_requested')
    change.append(
      h(
        'span',
        '',
        `${event.after?.model || 'Configured model'} · ${event.after?.provider || 'Configured provider'}`,
      ),
    );
  else if (event.action === 'model_completed')
    change.append(
      h(
        'span',
        '',
        `${human(event.after?.status)} · ${event.after?.candidates ?? 0} proposals · ${event.after?.rejected ?? 0} ${event.after?.rejected === 1 ? 'output' : 'outputs'} rejected by validation`,
      ),
    );
  else if (event.action === 'model_reject') {
    const candidate = event.before?.candidate;
    change.append(
      h(
        'span',
        '',
        candidate
          ? `${candidate.part_raw} · ${human(candidate.date_type)} · ${candidate.date ? dateText(candidate.date) : candidate.date_text || 'Unresolved'}`
          : 'Proposal retained as rejected',
      ),
    );
  } else if (event.action === 'model_accept') {
    const part = event.after?.part;
    const old = event.before?.part;
    const index = Number(event.field_path?.match(/\.dates\.(\d+)/)?.[1]);
    const date = part?.dates?.[index];
    if (old?.dates?.[index] && display(old.dates[index]) !== display(date))
      change.append(h('del', '', dateText(old.dates[index])), icon('chevron-right'));
    change.append(
      h(
        'span',
        '',
        `${display(part?.raw_identifier, 'Affected part')} · ${date ? `${human(date.kind)}: ${dateText(date)}` : 'Source-linked relationship applied'}`,
      ),
    );
  }
  return change;
}

function pendingModelRun(run) {
  return ['queued', 'running'].includes(run.status);
}
function fixtureModel(provider, model = '') {
  return /fixture/i.test(`${provider} ${model}`);
}
function formatRunTime(value) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf())
    ? 'Time unavailable'
    : parsed.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}
function modelDecisionFor(run, index) {
  return (run.decisions || []).find((decision) => Number(decision.candidate_index) === index);
}
function mergeModelRun(run) {
  state.modelRuns = [run, ...state.modelRuns.filter((item) => item.id !== run.id)];
}
function scheduleModelPoll(recordId) {
  clearTimeout(modelPollTimer);
  if (state.record?.id === recordId && state.modelRuns.some(pendingModelRun))
    modelPollTimer = setTimeout(() => pollModelRuns(recordId), 1200);
}
async function pollModelRuns(recordId) {
  try {
    const response = await api(`/api/notices/${encodeURIComponent(recordId)}/model-runs`);
    if (state.record?.id !== recordId) return;
    const hadPending = state.modelRuns.some(pendingModelRun);
    state.modelRuns = response.runs || [];
    state.modelError = null;
    renderModelReview();
    scheduleModelPoll(recordId);
    if (hadPending && !state.modelRuns.some(pendingModelRun)) {
      toast('Model review finished. Inspect the saved result before applying proposals.');
      loadHistory();
    }
  } catch (error) {
    if (state.record?.id === recordId) {
      state.modelError = `${error.message} Refresh model review to check the saved run.`;
      renderModelReview();
    }
  }
}
async function loadModelReview() {
  if (!state.record) return;
  const recordId = state.record.id;
  clearTimeout(modelPollTimer);
  state.modelLoading = true;
  state.modelError = null;
  renderModelReview();
  const results = await Promise.allSettled([
    api('/api/model'),
    api(`/api/notices/${encodeURIComponent(recordId)}/model-runs`),
  ]);
  if (state.record?.id !== recordId) return;
  state.modelLoading = false;
  if (results[0].status === 'fulfilled') state.modelConfig = results[0].value;
  else {
    state.modelConfig = null;
    state.modelError = results[0].reason.message;
  }
  if (results[1].status === 'fulfilled') state.modelRuns = results[1].value.runs || [];
  else state.modelError = results[1].reason.message;
  renderModelReview();
  scheduleModelPoll(recordId);
}
function renderModelReview() {
  const root = $('#model-content');
  root.replaceChildren();
  const config = state.modelConfig;
  const pending = state.modelStarting || state.modelRuns.some(pendingModelRun);
  const configCard = h('div', 'model-config');
  const heading = h('div', 'model-config-heading');
  heading.append(icon('link'), h('h4', '', 'Optional model review'));
  const fixture = fixtureModel(config?.provider || '', config?.model || '');
  const badge = h(
    'span',
    `model-mode-badge ${fixture ? 'fixture' : ''}`,
    state.modelLoading && !config
      ? 'Checking setup'
      : fixture
        ? 'Offline fixture'
        : config?.configured
          ? config.remote
            ? 'External provider'
            : 'Local model'
          : 'Not configured',
  );
  heading.append(badge);
  configCard.append(heading);
  if (config?.configured) {
    const identity = h('div', 'model-identity');
    identity.append(
      h('strong', '', config.model || 'Model not specified'),
      h('span', '', config.provider || 'Provider not specified'),
    );
    configCard.append(identity);
    configCard.append(
      h(
        'p',
        '',
        fixture
          ? 'Offline fixture output; no live model inference. Use this mode to test the proposal and review workflow.'
          : config.remote
            ? 'Running this review sends the bounded notice text to the configured external provider. Uploading a notice does not send it.'
            : 'Request additional part/date proposals from the configured local model. Each proposal requires your decision before it changes this record.',
      ),
    );
  } else
    configCard.append(
      h(
        'p',
        '',
        state.modelLoading
          ? 'Checking the provider configuration. The deterministic record remains available.'
          : 'The deterministic record is ready. Configure a model provider to request additional part/date proposals.',
      ),
    );
  if (config?.reason) configCard.append(h('p', 'model-setup-reason', config.reason));
  const actions = h('div', 'model-config-actions');
  const runButton = button(
    pending ? 'Model review in progress…' : 'Run model review',
    'button primary',
    runModelReview,
    pending ? undefined : 'plus',
  );
  runButton.id = 'run-model-review';
  runButton.disabled = !config?.configured || !config?.available || pending || state.modelLoading;
  if (pending) runButton.prepend(h('span', 'spinner'));
  const refresh = button('Refresh', 'button quiet', () => loadModelReview(), 'history');
  refresh.id = 'refresh-model-review';
  refresh.disabled = state.modelLoading || state.modelStarting;
  actions.append(runButton, refresh);
  configCard.append(actions);
  configCard.append(
    h(
      'p',
      'model-boundary',
      'No proposal is applied automatically. Accepted uncertainty remains explicit in the canonical record.',
    ),
  );
  root.append(configCard);
  if (state.modelError) {
    const error = h('div', 'form-error', state.modelError);
    error.id = 'model-error';
    error.setAttribute('role', 'alert');
    root.append(error);
  }
  const count = state.modelRuns.reduce(
    (sum, run) =>
      sum + (run.result?.candidates || []).filter((_, index) => !modelDecisionFor(run, index)).length,
    0,
  );
  $('#model-tab-count').hidden = !count;
  setText('#model-tab-count', count);
  if (state.view === 'model')
    setText(
      '#record-count',
      state.modelRuns.reduce((sum, run) => sum + (run.result?.candidates?.length || 0), 0),
    );
  if (!state.modelRuns.length) {
    const empty = h('div', 'model-empty');
    empty.append(
      icon(state.modelLoading ? 'history' : 'file'),
      h('h4', '', state.modelLoading ? 'Loading saved model runs…' : 'No model proposals yet.'),
      h(
        'p',
        '',
        state.modelLoading
          ? 'Previously requested runs and reviewer decisions are stored with this notice.'
          : config?.configured && config?.available
            ? 'Run model review when you want to inspect another extraction pass. Your current record stays in place.'
            : 'Set up a provider in the local run configuration, then refresh. Evidence review, BOM matching, and canonical export remain available.',
      ),
    );
    root.append(empty);
    return;
  }
  root.append(
    sectionLabel(
      'SAVED MODEL RUNS',
      `${state.modelRuns.length} ${state.modelRuns.length === 1 ? 'run' : 'runs'}`,
    ),
  );
  state.modelRuns.forEach((run, runIndex) => root.append(renderModelRun(run, runIndex)));
}
function renderModelRun(run, runIndex) {
  const result = run.result;
  const pending = pendingModelRun(run);
  const runNode = h('details', 'model-run');
  runNode.dataset.runId = run.id;
  runNode.open = runIndex === 0 || pending;
  const summary = h('summary', 'model-run-header');
  const title = h('span');
  title.append(
    h('strong', '', run.model || result?.model || 'Model run'),
    h('small', '', `${formatRunTime(run.created_at)} · Record v${run.base_version}`),
  );
  const names = {
    queued: 'Queued',
    running: 'Running',
    ok: 'Proposals ready',
    partial: 'Partial result',
    error: 'Run failed',
    unavailable: 'Unavailable',
  };
  summary.append(
    title,
    statusChip(
      ['ok'].includes(run.status) ? 'supported' : 'review_required',
      names[run.status] || human(run.status),
    ),
  );
  runNode.append(summary);
  const body = h('div', 'model-run-body');
  if (pending) {
    const waiting = h('div', 'model-run-pending');
    waiting.append(
      h('span', 'spinner'),
      h(
        'p',
        '',
        run.status === 'queued'
          ? 'This request is saved and waiting to run. Results will appear here.'
          : 'The configured model is processing this notice. You can return to the record; the result will be saved.',
      ),
    );
    body.append(waiting);
  }
  if (fixtureModel(run.provider || result?.provider || '', run.model || result?.model || ''))
    body.append(h('div', 'model-fixture-note', 'Offline fixture · No live model inference'));
  if (result) {
    const stats = h('div', 'model-run-meta');
    stats.append(
      h(
        'span',
        '',
        `${result.included_characters?.toLocaleString() ?? '—'} / ${result.input_characters?.toLocaleString() ?? '—'} source characters`,
      ),
      h('span', '', result.provider || run.provider),
    );
    body.append(stats);
    if (result.truncated) {
      const warning = h(
        'div',
        'callout warning',
        'Incomplete model context: some notice content was omitted or clipped. These proposals cannot establish complete affected-part coverage.',
      );
      warning.dataset.truncated = 'true';
      body.append(warning);
    }
    for (const error of result.errors || []) {
      const node = h(
        'div',
        'form-error',
        `${error} Check the provider configuration or runtime, then request a new run. The saved deterministic record is unchanged.`,
      );
      node.setAttribute('role', 'alert');
      body.append(node);
    }
    for (const warning of result.warnings || [])
      if (!/Offline fixture output/.test(warning)) body.append(h('p', 'model-run-warning', warning));
    if (run.base_version !== state.record?.version && !pending)
      body.append(
        h(
          'p',
          'model-version-note',
          `Requested from record v${run.base_version}; current record is v${state.record?.version}. Each acceptance is validated against the current record.`,
        ),
      );
    (result.candidates || []).forEach((candidate, index) =>
      body.append(renderModelCandidate(run, candidate, index)),
    );
    if (!result.candidates?.length && !['error', 'unavailable'].includes(result.status))
      body.append(
        h(
          'div',
          'model-no-candidates',
          result.rejected?.length
            ? 'No usable proposals remain after source validation. Nothing was applied.'
            : 'No candidate proposals were returned. The existing record is unchanged.',
        ),
      );
    if (result.rejected?.length) {
      const rejected = h('details', 'model-rejected-list');
      rejected.open = true;
      rejected.append(
        h(
          'summary',
          '',
          `${result.rejected.length} ${result.rejected.length === 1 ? 'output rejected' : 'outputs rejected'} by source validation`,
        ),
      );
      result.rejected.forEach((item) => {
        const node = h('div', 'model-rejection');
        node.append(
          h('strong', '', item.part_raw || `Output ${Number(item.candidate_index) + 1}`),
          h('p', '', (item.reasons || [item.reason || 'Source validation failed']).map(human).join(' · ')),
        );
        rejected.append(node);
      });
      body.append(rejected);
    }
  }
  runNode.append(body);
  return runNode;
}
function matchingCandidateParts(candidate) {
  return (state.record?.parts || []).filter(
    (part) => display(part.raw_identifier, '') === candidate.part_raw,
  );
}
function currentCandidateValue(candidate, partId) {
  const parts = matchingCandidateParts(candidate).filter((part) => !partId || part.id === partId);
  if (!parts.length) return 'No affected-part record';
  if (parts.length > 1)
    return `${parts.length} exact identifiers in different part records — select the intended scope`;
  const dates = parts[0].dates.filter((date) => date.kind === candidate.date_type);
  return dates.length ? dates.map((date) => dateText(date)).join(' · ') : 'No relationship recorded';
}
function inspectModelCandidate(run, candidate, index) {
  selectEvidence(candidate.evidence || []);
  setText(
    '#evidence-caption-text',
    `Model proposal · ${candidate.part_raw} · ${human(candidate.date_type)}${candidate.evidence?.[0] ? ` · page ${candidate.evidence[0].page}` : ''}`,
  );
  $$('.proposal-card').forEach((node) =>
    node.classList.toggle(
      'selected',
      node.dataset.runId === run.id && Number(node.dataset.candidateIndex) === index,
    ),
  );
}
function renderModelCandidate(run, candidate, index) {
  const decision = modelDecisionFor(run, index);
  const card = h('article', `proposal-card ${decision ? 'decided' : ''}`);
  card.dataset.runId = run.id;
  card.dataset.candidateIndex = index;
  const heading = h('div', 'proposal-heading');
  heading.append(
    h('code', '', candidate.part_raw),
    statusChip(
      decision?.action === 'accept' ? 'accepted' : 'review_required',
      decision ? (decision.action === 'accept' ? 'Applied' : 'Rejected') : 'Pending decision',
    ),
  );
  card.append(heading);
  const comparison = h('div', 'proposal-comparison');
  const current = h('div');
  current.append(
    h('span', '', `CURRENT ${human(candidate.date_type).toUpperCase()}`),
    h('strong', '', currentCandidateValue(candidate)),
  );
  const proposed = h('div');
  proposed.append(
    h('span', '', `PROPOSED ${human(candidate.date_type).toUpperCase()}`),
    h('strong', '', candidate.date ? dateText(candidate.date) : 'Unresolved'),
  );
  comparison.append(current, icon('chevron-right'), proposed);
  card.append(comparison);
  card.append(
    h('p', 'proposal-source-value', `Source value: ${candidate.date_text || 'No exact date in source'}`),
  );
  if (candidate.exception)
    card.append(h('p', 'proposal-exception', `Part exception: ${candidate.exception}`));
  if (!candidate.date)
    card.append(
      h(
        'p',
        'proposal-unresolved',
        'Accepting this proposal retains a review-required date; it does not invent an exact deadline.',
      ),
    );
  const excerpt = h(
    'blockquote',
    'proposal-evidence',
    (candidate.evidence || []).map((item) => `Page ${item.page} · ${item.quote}`).join('\n\n'),
  );
  card.append(excerpt);
  const actions = h('div', 'proposal-actions');
  actions.append(
    button(
      'Inspect source',
      'button quiet compact',
      () => inspectModelCandidate(run, candidate, index),
      'link',
    ),
  );
  if (decision) {
    const description = h('div', 'proposal-decision');
    description.append(
      h('strong', '', `${decision.action === 'accept' ? 'Applied' : 'Rejected'} by ${decision.reviewer}`),
      h('p', '', decision.reason),
      h(
        'small',
        '',
        `${formatRunTime(decision.created_at)}${decision.version ? ` · Record v${decision.version}` : ''}`,
      ),
    );
    card.append(description);
  } else {
    actions.append(
      button('Reject', 'button secondary compact', () => openProposalDecision(run, index, 'reject')),
      button('Accept', 'button primary compact', () => openProposalDecision(run, index, 'accept'), 'check'),
    );
  }
  card.append(actions);
  return card;
}
async function runModelReview() {
  if (
    !state.record ||
    state.modelStarting ||
    state.modelRuns.some(pendingModelRun) ||
    !state.modelConfig?.available
  )
    return;
  const recordId = state.record.id;
  state.modelStarting = true;
  state.modelError = null;
  renderModelReview();
  try {
    const result = await api(`/api/notices/${encodeURIComponent(recordId)}/model-runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_version: state.record.version }),
    });
    if (state.record?.id !== recordId) return;
    mergeModelRun(result.run || result);
    scheduleModelPoll(recordId);
    loadHistory();
  } catch (error) {
    if (state.record?.id === recordId)
      state.modelError =
        error.status === 409
          ? `${error.message} Reload the notice before requesting a new run.`
          : error.message;
  } finally {
    if (state.record?.id === recordId) {
      state.modelStarting = false;
      renderModelReview();
    }
  }
}
function openProposalDecision(run, index, action) {
  const candidate = run.result?.candidates?.[index];
  if (!candidate) return;
  state.modelDecision = { runId: run.id, index, action, candidate };
  clearError('#proposal-error');
  setText('#proposal-dialog-title', action === 'accept' ? 'Accept model proposal' : 'Reject model proposal');
  setText('#proposal-submit', action === 'accept' ? 'Accept proposal' : 'Reject proposal');
  $('#proposal-reason').value = '';
  $('#proposal-reviewer').value = localStorage.getItem('noticeforge-reviewer') || '';
  const root = $('#proposal-review-context');
  root.replaceChildren();
  if (fixtureModel(run.provider || '', run.model || ''))
    root.append(h('p', 'model-fixture-note', 'Offline fixture · No live model inference'));
  const summary = h('div', 'review-original');
  summary.append(
    h('span', '', `${candidate.part_raw} · ${human(candidate.date_type)}`),
    h('strong', '', candidate.date ? dateText(candidate.date) : `Unresolved: ${candidate.date_text}`),
    h('p', '', `${run.model} · ${run.provider}`),
  );
  root.append(summary);
  root.append(
    h(
      'blockquote',
      'proposal-evidence',
      (candidate.evidence || []).map((item) => `Page ${item.page} · ${item.quote}`).join('\n\n'),
    ),
  );
  root.append(
    h(
      'p',
      'review-scope',
      action === 'reject'
        ? 'The proposal remains in the saved run with your rejection reason. The canonical record is unchanged.'
        : candidate.date
          ? 'Your decision applies this source-linked relationship to the canonical record and records the model provenance.'
          : 'This applies an unresolved relationship with source evidence. Its date remains review-required.',
    ),
  );
  const targets = $('#proposal-target-fields');
  targets.replaceChildren();
  if (action === 'accept') {
    const matches = matchingCandidateParts(candidate);
    if (matches.length > 1) {
      const label = h('label', '', 'Affected part record');
      label.htmlFor = 'proposal-target-part';
      const select = h('select', 'proposal-select');
      select.id = 'proposal-target-part';
      select.required = true;
      const empty = h('option', '', 'Select the exact part scope');
      empty.value = '';
      select.append(empty);
      matches.forEach((part) => {
        const option = h(
          'option',
          '',
          `${display(part.raw_identifier)} · ${display(part.manufacturer)} · ${part.group}`,
        );
        option.value = part.id;
        select.append(option);
      });
      select.addEventListener('change', () => renderProposalDateTarget(candidate, select.value));
      targets.append(label, select);
    }
    renderProposalDateTarget(candidate, matches.length === 1 ? matches[0].id : '');
  }
  inspectModelCandidate(run, candidate, index);
  showDialog('#proposal-dialog');
}
function renderProposalDateTarget(candidate, partId) {
  $('#proposal-date-target')?.remove();
  const part = state.record.parts.find((item) => item.id === partId);
  if (!part) return;
  const dates = part.dates
    .map((date, index) => ({ date, index }))
    .filter((item) => item.date.kind === candidate.date_type);
  if (dates.length < 2) return;
  const wrapper = h('div');
  wrapper.id = 'proposal-date-target';
  const label = h('label', '', 'Existing relationship to replace');
  label.htmlFor = 'proposal-replace-date';
  const select = h('select', 'proposal-select');
  select.id = 'proposal-replace-date';
  select.required = true;
  const empty = h('option', '', 'Select the intended relationship');
  empty.value = '';
  select.append(empty);
  dates.forEach(({ date, index }) => {
    const option = h(
      'option',
      '',
      `${dateText(date)} · ${human(date.qualifier)} · relationship ${index + 1}`,
    );
    option.value = String(index);
    select.append(option);
  });
  wrapper.append(label, select);
  $('#proposal-target-fields').append(wrapper);
}
async function submitProposalDecision(event) {
  event.preventDefault();
  if (!state.modelDecision || !state.record) return;
  clearError('#proposal-error');
  const submit = $('#proposal-submit');
  setBusy(submit, true, 'Saving decision…');
  const decision = state.modelDecision;
  const recordId = state.record.id;
  const body = {
    candidate_index: decision.index,
    action: decision.action,
    reviewer: $('#proposal-reviewer').value.trim(),
    reason: $('#proposal-reason').value.trim(),
    expected_version: state.record.version,
  };
  if (decision.action === 'accept') {
    const matches = matchingCandidateParts(decision.candidate);
    const targetPart = $('#proposal-target-part')?.value || (matches.length === 1 ? matches[0].id : null);
    if (targetPart) body.target_part_id = targetPart;
    if ($('#proposal-replace-date')?.value)
      body.replace_date_index = Number($('#proposal-replace-date').value);
  }
  try {
    const response = await api(
      `/api/notices/${encodeURIComponent(recordId)}/model-runs/${encodeURIComponent(decision.runId)}/decisions`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
    );
    if (state.record?.id !== recordId) return;
    state.record = response.record;
    mergeModelRun(response.run);
    localStorage.setItem('noticeforge-reviewer', body.reviewer);
    $('#proposal-dialog').close();
    renderRecord();
    switchView('model');
    inspectModelCandidate(response.run, decision.candidate, decision.index);
    await Promise.allSettled([refreshList(), loadHistory()]);
    renderModelReview();
    toast(
      decision.action === 'accept'
        ? 'Proposal applied. Source evidence and model provenance are preserved.'
        : 'Proposal rejected. Your reason is saved with the run.',
    );
  } catch (error) {
    showError(
      '#proposal-error',
      error.status === 409
        ? `${error.message} Reload this notice to review the latest record before deciding.`
        : error,
    );
    if (error.status === 409)
      $('#proposal-error').append(
        button('Reload notice', 'button secondary compact', () => {
          $('#proposal-dialog').close();
          loadNotice(recordId);
        }),
      );
  } finally {
    setBusy(submit, false);
  }
}

function parseBOM(text) {
  const rows = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) continue;
    let cells = [];
    if (line.includes('\t')) cells = line.split('\t');
    else {
      let cell = '';
      let quoted = false;
      for (let index = 0; index < line.length; index++) {
        const char = line[index];
        if (char === '"') {
          if (quoted && line[index + 1] === '"') {
            cell += '"';
            index++;
          } else quoted = !quoted;
        } else if (char === ',' && !quoted) {
          cells.push(cell);
          cell = '';
        } else cell += char;
      }
      if (quoted) throw new Error('A CSV quotation is not closed. Check the BOM input.');
      cells.push(cell);
    }
    if (!rows.length && ['part_number', 'part number', 'mpn', 'part'].includes(cells[0].trim().toLowerCase()))
      continue;
    if (cells.length > 2)
      throw new Error(
        'Use two columns: part number and optional manufacturer. Put fields containing commas in quotation marks.',
      );
    const part = cells[0].trim();
    if (!part) throw new Error('Each BOM row needs a part number.');
    const row = { part_number: part };
    if (cells[1]?.trim()) row.manufacturer = cells[1].trim();
    rows.push(row);
  }
  if (!rows.length) throw new Error('Enter at least one part number.');
  if (rows.length > 10000) throw new Error('Limit each comparison to 10,000 BOM rows.');
  return rows;
}
async function submitBOM(event) {
  event.preventDefault();
  if (!state.record) return;
  clearError('#bom-error');
  const submit = $('#bom-form button[type=submit]');
  const recordId = state.record.id;
  const workspaceRequest = state.request;
  const token = ++bomRequest;
  const currentContext = () =>
    token === bomRequest && workspaceRequest === state.request && state.record?.id === recordId;
  try {
    const rows = parseBOM($('#bom-input').value);
    setBusy(submit, true, 'Matching…');
    const result = await api(`/api/notices/${encodeURIComponent(recordId)}/bom`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rows }),
    });
    if (!currentContext()) return;
    state.bom = result.matches || [];
    renderBOMResults(rows);
    $('#bom-tab-count').hidden = false;
    setText('#bom-tab-count', state.bom.length);
  } catch (error) {
    if (currentContext()) showError('#bom-error', error);
  } finally {
    if (token === bomRequest) setBusy(submit, false);
  }
}
function renderBOMEmpty() {
  const root = $('#bom-results');
  root.replaceChildren();
  const empty = h('div', 'inline-empty');
  empty.append(
    icon('search'),
    h('h4', '', 'Bring your BOM into focus.'),
    h('p', '', 'Literal matches, manufacturer ambiguity, and unmatched parts will appear here.'),
  );
  root.append(empty);
  setText('#bom-result-summary', 'Awaiting input');
}
function renderBOMResults(rows) {
  const root = $('#bom-results');
  root.replaceChildren();
  let literal = 0;
  state.bom.forEach((match, index) => {
    const status = match.status || match.result || 'unmatched';
    const isMatch = ['match', 'matched', 'literal_match', 'exact', 'exact_match'].includes(status);
    const isAmbiguous = status.includes('ambiguous');
    if (isMatch) literal++;
    const card = h('div', 'bom-match');
    const header = h('div', 'bom-match-header');
    const query = match.query || match.input || match.bom_row || rows[index] || {};
    header.append(
      h('code', '', match.part_number || query.part_number || rows[index]?.part_number || 'Unknown part'),
      statusChip(
        isMatch ? 'supported' : isAmbiguous ? 'review_required' : 'incomplete',
        isMatch ? 'Literal match' : isAmbiguous ? 'Ambiguous' : 'Unmatched',
      ),
    );
    card.append(header);
    const manufacturer = match.manufacturer || query.manufacturer || rows[index]?.manufacturer;
    card.append(h('p', '', manufacturer || 'Manufacturer not supplied'));
    const reason = match.reason || match.message;
    if (reason) card.append(h('small', '', reason));
    const candidates = match.matches || match.candidates || match.part_ids || [];
    if (candidates.length)
      card.append(
        h(
          'small',
          '',
          `Notice records: ${candidates.map((item) => (typeof item === 'string' ? item : item.part_number || item.raw_identifier?.value || item.id || 'Affected record')).join(', ')}`,
        ),
      );
    root.append(card);
  });
  setText(
    '#bom-result-summary',
    `${literal} literal ${literal === 1 ? 'match' : 'matches'} / ${state.bom.length} rows`,
  );
  if (!state.bom.length)
    root.append(h('p', 'subtle', 'No results were returned. Check the input and try again.'));
}

function openUpload() {
  clearError('#upload-error');
  $('#file-input').value = '';
  setText('#file-label', 'Choose a notice or drop it here');
  showDialog('#upload-dialog');
}
function updateFileLabel() {
  const file = $('#file-input').files[0];
  setText('#file-label', file ? file.name : 'Choose a notice or drop it here');
  clearError('#upload-error');
}
async function uploadNotice(event) {
  event.preventDefault();
  const file = $('#file-input').files[0];
  if (!file) return;
  clearError('#upload-error');
  if (!/\.(pdf|txt)$/i.test(file.name)) {
    showError('#upload-error', 'Choose a PDF or plain text (.txt) notice.');
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    showError('#upload-error', 'This file is larger than 10 MiB. Import a smaller notice.');
    return;
  }
  if (!file.size) {
    showError('#upload-error', 'The selected file is empty. Choose a notice with source content.');
    return;
  }
  const submit = $('#upload-submit');
  setBusy(submit, true, 'Extracting locally…');
  const body = new FormData();
  body.append('file', file);
  try {
    const record = await api('/api/notices', { method: 'POST', body });
    $('#upload-dialog').close();
    state.view = 'review';
    await refreshList();
    await loadNotice(record.id, record);
    toast('Notice imported. Its evidence and review items are ready.');
  } catch (error) {
    showError('#upload-error', error);
  } finally {
    setBusy(submit, false);
  }
}
function openExport() {
  if (!state.record) return;
  clearError('#export-error');
  const count = reviewCount();
  $('#export-warning').hidden = !count && state.record.document.complete;
  if (!$('#export-warning').hidden)
    setText(
      '#export-warning',
      !state.record.document.complete
        ? 'This source is incomplete. The canonical record includes that coverage warning.'
        : `${count} review ${count === 1 ? 'item remains' : 'items remain'} open. Their uncertainty remains explicit in the canonical export.`,
    );
  showDialog('#export-dialog');
}
async function exportRecord(format, node) {
  if (!state.record) return;
  clearError('#export-error');
  node.disabled = true;
  try {
    const response = await request(
      `/api/notices/${encodeURIComponent(state.record.id)}/export?format=${format}`,
    );
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = h('a');
    link.href = url;
    const disposition = response.headers.get('Content-Disposition') || '';
    const file = disposition.match(/filename="?([^";]+)"?/i)?.[1];
    link.download =
      file ||
      `${display(state.record.metadata.notice_id, 'notice').replace(/[^a-zA-Z0-9._-]/g, '_')}.${format === 'json' ? 'json' : 'xml'}`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    toast(format === 'json' ? 'Canonical record exported.' : 'Validated smartPCN export downloaded.');
  } catch (error) {
    showError('#export-error', error);
  } finally {
    node.disabled = false;
  }
}

$$('[data-close]').forEach((node) =>
  node.addEventListener('click', () => $(`#${node.dataset.close}`).close()),
);
$$('dialog').forEach((dialog) => {
  const heading = $('h2', dialog);
  if (heading) {
    if (!heading.id) heading.id = `${dialog.id}-title`;
    dialog.setAttribute('aria-labelledby', heading.id);
  }
  dialog.addEventListener('keydown', (event) => {
    if (event.key !== 'Tab') return;
    const focusable = $$(
      'button:not([disabled]), a[href], input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      dialog,
    ).filter((node) => node.getClientRects().length && !node.closest('[hidden]'));
    const first = focusable[0];
    const last = focusable.at(-1);
    if (!first) {
      event.preventDefault();
      return;
    }
    if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
      event.preventDefault();
      last.focus();
    } else if (
      !event.shiftKey &&
      (document.activeElement === last || !dialog.contains(document.activeElement))
    ) {
      event.preventDefault();
      first.focus();
    }
  });
  dialog.addEventListener('click', (event) => {
    if (event.target !== dialog) return;
    const box = dialog.getBoundingClientRect();
    if (
      event.clientX < box.left ||
      event.clientX > box.right ||
      event.clientY < box.top ||
      event.clientY > box.bottom
    )
      dialog.close();
  });
});
$$('[data-view]').forEach((node) => node.addEventListener('click', () => switchView(node.dataset.view)));
$('.workspace-tabs').addEventListener('keydown', (event) => {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  const tabs = $$('.workspace-tab');
  const current = tabs.findIndex((tab) => tab === document.activeElement);
  if (current === -1) return;
  event.preventDefault();
  const index =
    event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? tabs.length - 1
        : (current + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
  tabs[index].focus();
  switchView(tabs[index].dataset.view);
});
['#upload-button', '#sidebar-upload', '#empty-upload'].forEach((id) =>
  $(id).addEventListener('click', openUpload),
);
['#open-queue', '#switch-notice'].forEach((id) =>
  $(id).addEventListener('click', () => {
    renderQueue();
    showDialog('#queue-dialog');
  }),
);
$('#queue-import').addEventListener('click', () => {
  $('#queue-dialog').close();
  openUpload();
});
$('#queue-search').addEventListener('input', renderQueue);
$('#help-button').addEventListener('click', () => showDialog('#about-dialog'));
$('#export-button').addEventListener('click', openExport);
$$('[data-export]').forEach((node) =>
  node.addEventListener('click', () => exportRecord(node.dataset.export, node)),
);
$('#page-prev').addEventListener('click', () => changePage(-1));
$('#page-next').addEventListener('click', () => changePage(1));
$('#selected-review').addEventListener('click', () => {
  if (state.selected?.path) openReview(state.selected.path);
});
$('#zoom-in').addEventListener('click', () => zoomSource(0.25));
$('#zoom-out').addEventListener('click', () => zoomSource(-0.25));
$('#zoom-fit').addEventListener('click', () => zoomSource(0));
$('#upload-form').addEventListener('submit', uploadNotice);
$('#file-input').addEventListener('change', updateFileLabel);
$('#review-form').addEventListener('submit', submitReview);
$('#bom-form').addEventListener('submit', submitBOM);
$('#proposal-form').addEventListener('submit', submitProposalDecision);
$$('input[name=action]').forEach((input) =>
  input.addEventListener('change', () => {
    const correcting = input.value === 'correct' && input.checked;
    $('#correction-field').hidden = !correcting;
    $('#corrected-value').required = correcting;
    if (correcting) $('#corrected-value').focus();
  }),
);
$('#bom-example').addEventListener('click', () => {
  if (!state.record) return;
  const quote = (value) => (/[,"\r\n]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value);
  $('#bom-input').value = [
    'part_number,manufacturer',
    ...state.record.parts.map(
      (part) => `${quote(display(part.raw_identifier, ''))},${quote(display(part.manufacturer, ''))}`,
    ),
  ].join('\n');
  $('#bom-input').focus();
});
const dropzone = $('#dropzone');
['dragenter', 'dragover'].forEach((type) =>
  dropzone.addEventListener(type, (event) => {
    event.preventDefault();
    dropzone.classList.add('dragging');
  }),
);
['dragleave', 'drop'].forEach((type) =>
  dropzone.addEventListener(type, () => dropzone.classList.remove('dragging')),
);
dropzone.addEventListener('drop', (event) => {
  event.preventDefault();
  if (event.dataTransfer.files.length) {
    const transfer = new DataTransfer();
    transfer.items.add(event.dataTransfer.files[0]);
    $('#file-input').files = transfer.files;
    updateFileLabel();
  }
});
loadWorkspace();
