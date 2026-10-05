// Every number on the page comes from data/*.json. Nothing numeric is written in the HTML.
(async function () {
  const DATA = new URLSearchParams(location.search).get("data") || "data";
  const load = (name) => fetch(`${DATA}/${name}.json`).then((r) => r.json());
  const [results, modelsFile, examples] = await Promise.all([load("results"), load("models"), load("examples")]);

  const FAMILY = (id) => id.split("/")[0];
  const FAMILY_NAME = { openai: "OpenAI", anthropic: "Anthropic", google: "Google" };
  const SHAPE = { openai: d3.symbolCircle, anthropic: d3.symbolSquare, google: d3.symbolTriangle };
  const color = (id) => `var(--fam-${FAMILY(id)})`;
  const shortName = (m) => (modelsFile.models[m.model || m]?.name || m.model || m).replace(/^[^:]+:\s*/, "");

  const fmt = {
    int: (v) => d3.format(",")(v),
    pct: (v) => `${Math.round(v * 100)}%`,
    pct1: (v) => `${(v * 100).toFixed(1)}%`,
    points: (v) => `${Math.round(v * 100)} percentage points`,
    kappa: (v) => v.toFixed(2),
    usd: (v) => (v >= 1 ? `$${v.toFixed(2)}` : `$${v.toPrecision(2)}`),
    date: (v) => v.slice(0, 10),
    name: (v) => v.replace(/^[^:]+:\s*/, ""),
    name2: (id) => shortName(id),
    pctrange: ([a, b]) => (Math.round(a * 100) === Math.round(b * 100) ? `${Math.round(a * 100)}%`
      : `${Math.round(a * 100)}–${Math.round(b * 100)}%`),
    intrange: ([a, b]) => (Math.round(a) === Math.round(b) ? `${Math.round(a)}` : `${Math.round(a)}–${Math.round(b)}`),
    centsrange: ([a, b]) => `${Math.round(a * 100)}–${Math.round(b * 100)} cents`,
    label: (v) => ({ supports: "supported", contradicts: "contradicted", not_enough_info: "not enough information",
      not_supported: "not supported" }[v] || v),
    price: (v) => `$${+v.toFixed(4)}`,
    models: (ids) => ids.map(shortName).join(", "),
    excluded: (obj) => Object.entries(obj).map(([id, why]) => `${id.split("/")[1]} (${why})`).join("; "),
  };
  const get = (path) => path.split(".").reduce((o, k) => (o == null ? o : o[k]), results);

  // 1. bound text (recorded in window.__bindings for the automated page check)
  window.__bindings = [];
  document.querySelectorAll("[data-bind]").forEach((el) => {
    const value = get(el.dataset.bind);
    el.textContent = value == null ? "n/a" : el.dataset.format ? fmt[el.dataset.format](value) : value;
    window.__bindings.push({ path: el.dataset.bind, value, text: el.textContent });
  });

  // sentences that are only true for some results are shown or hidden by a boolean in the data
  document.querySelectorAll("[data-show]").forEach((el) => { el.hidden = !get(el.dataset.show); });

  const models = results.models;

  // 2. charts: one per dataset, shared x-scale (cost) so the panels compare directly
  const tooltip = document.getElementById("tooltip");
  function showTip(event, m, dataset) {
    const s = m[dataset];
    tooltip.replaceChildren();
    const value = document.createElement("strong");
    value.textContent = `${fmt.pct1(s.accuracy)} accurate`;
    const name = document.createElement("span");
    name.className = "name";
    const key = document.createElement("span");
    key.className = "key";
    key.style.background = color(m.model);
    name.append(key, document.createTextNode(`${shortName(m)} · ${FAMILY_NAME[FAMILY(m.model)]}`));
    const rest = document.createElement("span");
    rest.textContent = `95% interval ${fmt.pct1(s.accuracy_ci[0])}–${fmt.pct1(s.accuracy_ci[1])} · ` +
      `${fmt.usd(m.cost_per_1000_usd)} per 1,000 checks · ${fmt.usd(m.cost_per_manuscript_usd)} per paper`;
    tooltip.append(value, name, rest);
    tooltip.hidden = false;
    const box = (event.target.getBoundingClientRect ? event.target : event.currentTarget).getBoundingClientRect();
    const x = Math.min(box.right + 12, window.innerWidth - tooltip.offsetWidth - 8);
    tooltip.style.left = `${Math.max(8, x)}px`;
    tooltip.style.top = `${Math.max(8, box.top - 8)}px`;
  }
  const hideTip = () => { tooltip.hidden = true; };

  const costs = models.map((m) => m.cost_per_1000_usd);
  const xDomain = [d3.min(costs) / 1.6, d3.max(costs) * 1.6];

  function chart(el, dataset, frontierIds) {
    el.replaceChildren();
    const W = Math.max(300, el.clientWidth), H = W < 500 ? 280 : 320;
    const M = { top: 16, right: 16, bottom: 44, left: 44 };
    const pts = models.filter((m) => m[dataset]);
    const lows = pts.map((m) => m[dataset].accuracy_ci[0]);
    const x = d3.scaleLog().domain(xDomain).range([M.left, W - M.right]);
    const y = d3.scaleLinear().domain([Math.max(0, Math.floor(d3.min(lows) * 10) / 10 - 0.05), 1])
      .range([H - M.bottom, M.top]).nice();
    const svg = d3.select(el).append("svg").attr("width", W).attr("height", H).attr("viewBox", `0 0 ${W} ${H}`);

    svg.append("g").attr("class", "grid").selectAll("line").data(y.ticks(5)).join("line")
      .attr("x1", M.left).attr("x2", W - M.right).attr("y1", y).attr("y2", y);
    svg.append("g").attr("transform", `translate(0,${H - M.bottom})`)
      .call(d3.axisBottom(x).ticks(4, (v) => fmt.usd(v)).tickSizeOuter(0));
    svg.append("g").attr("transform", `translate(${M.left},0)`)
      .call(d3.axisLeft(y).ticks(5, "%").tickSize(0).tickPadding(6)).call((g) => g.select(".domain").remove());
    svg.append("text").attr("x", (M.left + W - M.right) / 2).attr("y", H - 6).attr("text-anchor", "middle")
      .text("Cost per 1,000 checks (log scale)");

    const frontier = pts.filter((m) => frontierIds.includes(m.model))
      .sort((a, b) => a.cost_per_1000_usd - b.cost_per_1000_usd);
    svg.append("path").attr("class", "frontier")
      .attr("d", d3.line().x((m) => x(m.cost_per_1000_usd)).y((m) => y(m[dataset].accuracy)).curve(d3.curveStepAfter)(frontier));

    const g = svg.append("g").selectAll("g").data(pts).join("g").attr("class", "point");
    g.append("line").attr("class", "ci").attr("stroke", (m) => color(m.model))
      .attr("x1", (m) => x(m.cost_per_1000_usd)).attr("x2", (m) => x(m.cost_per_1000_usd))
      .attr("y1", (m) => y(m[dataset].accuracy_ci[0])).attr("y2", (m) => y(m[dataset].accuracy_ci[1]));
    g.append("circle").attr("class", "hit").attr("r", 14).attr("tabindex", 0)
      .attr("cx", (m) => x(m.cost_per_1000_usd)).attr("cy", (m) => y(m[dataset].accuracy))
      .attr("aria-label", (m) => `${shortName(m)}: ${fmt.pct1(m[dataset].accuracy)} accurate, ${fmt.usd(m.cost_per_1000_usd)} per 1,000 checks`)
      .on("pointerenter focus", function (event, m) { this.parentNode.classList.add("active"); showTip(event, m, dataset); })
      .on("pointerleave blur", function () { this.parentNode.classList.remove("active"); hideTip(); });
    g.append("path").attr("class", "dot").attr("fill", (m) => color(m.model))
      .attr("d", (m) => d3.symbol(SHAPE[FAMILY(m.model)], 90)())
      .attr("transform", (m) => `translate(${x(m.cost_per_1000_usd)},${y(m[dataset].accuracy)})`)
      .attr("pointer-events", "none");

    // direct labels, placed greedily so none overlap; a label that cannot fit is left to the
    // tooltip and the table (always open below the chart)
    const placed = [];
    const overlaps = (b) => placed.some((p) => b.x0 < p.x1 && b.x1 > p.x0 && b.y0 < p.y1 && b.y1 > p.y0)
      || pts.some((m) => { const px = x(m.cost_per_1000_usd), py = y(m[dataset].accuracy);
        return px > b.x0 - 6 && px < b.x1 + 6 && py > b.y0 - 6 && py < b.y1 + 6; });
    const labelLayer = svg.append("g");
    for (const m of [...pts].sort((a, b) => b[dataset].accuracy - a[dataset].accuracy)) {
      const text = shortName(m), w = text.length * 6.2, px = x(m.cost_per_1000_usd), py = y(m[dataset].accuracy);
      const options = [[px + 10, py - 6, "start"], [px - 10, py - 6, "end"], [px + 10, py + 10, "start"],
                       [px - 10, py + 10, "end"], [px - w / 2, py - 14, "start"], [px - w / 2, py + 20, "start"]];
      for (const [lx, ly, anchor] of options) {
        const x0 = anchor === "end" ? lx - w : lx;
        const box = { x0, x1: x0 + w, y0: ly - 11, y1: ly + 2 };
        if (box.x0 < M.left || box.x1 > W - 2 || box.y0 < 0 || box.y1 > H - M.bottom || overlaps(box)) continue;
        placed.push(box);
        labelLayer.append("text").attr("class", "label").attr("x", lx).attr("y", ly).attr("text-anchor", anchor).text(text);
        break;
      }
    }
  }

  const drawCharts = () => {
    chart(document.getElementById("chart-scifact"), "scifact", results.pareto_frontier_scifact);
    chart(document.getElementById("chart-arxiv"), "arxiv", results.pareto_frontier_arxiv || []);
  };
  drawCharts();
  let lastWidth = document.getElementById("chart-scifact").clientWidth;
  window.addEventListener("resize", () => {
    const width = document.getElementById("chart-scifact").clientWidth;
    if (width !== lastWidth) { lastWidth = width; drawCharts(); }
  });

  // legend: family = color + shape
  const legend = document.getElementById("legend");
  for (const fam of ["openai", "anthropic", "google"]) {
    if (!models.some((m) => FAMILY(m.model) === fam)) continue;
    const item = document.createElement("span");
    item.innerHTML = `<svg viewBox="-6 -6 12 12"><path d="${d3.symbol(SHAPE[fam], 40)()}" fill="var(--fam-${fam})"/></svg>`;
    item.append(document.createTextNode(FAMILY_NAME[fam]));
    legend.append(item);
  }

  // text summary of the charts (also serves screen readers)
  const bySci = models.filter((m) => m.scifact).sort((a, b) => b.scifact.accuracy - a.scifact.accuracy);
  const cheapest = [...models].sort((a, b) => a.cost_per_1000_usd - b.cost_per_1000_usd)[0];
  const byArx = models.filter((m) => m.arxiv).sort((a, b) => b.arxiv.accuracy - a.arxiv.accuracy);
  const summary = `On SciFact, accuracy ranged from ${fmt.pct(bySci.at(-1).scifact.accuracy)} (${shortName(bySci.at(-1))}) ` +
    `to ${fmt.pct(bySci[0].scifact.accuracy)} (${shortName(bySci[0])}); on the arXiv citations, from ` +
    `${fmt.pct(byArx.at(-1).arxiv.accuracy)} (${shortName(byArx.at(-1))}) to ${fmt.pct(byArx[0].arxiv.accuracy)} ` +
    `(${shortName(byArx[0])}). The cheapest model, ${shortName(cheapest)}, cost ${fmt.usd(cheapest.cost_per_1000_usd)} ` +
    `per 1,000 checks. Overlapping intervals mean those differences are not all reliable.`;
  document.getElementById("chart-summary").textContent = summary;
  document.getElementById("chart-scifact").setAttribute("aria-label", summary);
  document.getElementById("chart-arxiv").setAttribute("aria-label",
    "Accuracy on real versus swapped arXiv citations, per model, against cost. Values are in the table below.");

  // refusals: counted as failed checks, and said so
  const refusing = models.filter((m) => m.refusals > 0);
  if (refusing.length) {
    const note = document.getElementById("refusal-note");
    note.textContent = refusing.map((m) => {
      const where = Object.entries(m.refusals_by_dataset || {}).map(([d, n]) => `${fmt.int(n)} ${d === "scifact" ? "SciFact" : "arXiv"}`).join(", ");
      return `${shortName(m)} declined ${fmt.int(m.refusals)} checks (${where})`;
    }).join("; ") + ". A declined check counts as a failed check in the accuracy above; the table also shows accuracy on the checks each model answered.";
    note.hidden = false;
  }

  // 3. table
  const tbody = document.querySelector("#model-table tbody");
  for (const m of [...models].sort((a, b) => a.cost_per_1000_usd - b.cost_per_1000_usd)) {
    const tr = document.createElement("tr");
    const cell = (text, cls, sub) => {
      const td = document.createElement("td");
      if (cls) td.className = cls;
      td.append(document.createTextNode(text));
      if (sub) { const s = document.createElement("span"); s.className = "sub"; s.textContent = sub; td.append(s); }
      tr.append(td);
    };
    const name = document.createElement("td");
    const sw = document.createElement("span");
    sw.className = "swatch"; sw.style.background = color(m.model);
    const price = document.createElement("span");
    price.className = "sub";
    price.textContent = `${fmt.price(m.price_per_million.input)} / ${fmt.price(m.price_per_million.output)} per 1M tokens`;
    name.className = "model-cell";
    name.append(sw, document.createTextNode(shortName(m)), price);
    tr.append(name);
    const ci = (s) => `${fmt.pct1(s.accuracy_ci[0])}–${fmt.pct1(s.accuracy_ci[1])}`;
    const answered = (s) => (s.answered_accuracy != null && s.answered_accuracy !== s.accuracy
      ? ` · ${fmt.pct1(s.answered_accuracy)} of answered` : "");
    cell(m.scifact ? fmt.pct1(m.scifact.accuracy) : "n/a", "num",
         m.scifact && `${ci(m.scifact)} · macro-F1 ${m.scifact.macro_f1.toFixed(2)}${answered(m.scifact)}`);
    cell(m.arxiv ? fmt.pct1(m.arxiv.accuracy) : "n/a", "num", m.arxiv && ci(m.arxiv) + answered(m.arxiv));
    cell(fmt.int(m.refusals || 0), "num");
    cell(fmt.usd(m.cost_per_1000_usd), "num");
    cell(fmt.usd(m.cost_per_manuscript_usd), "num");
    tbody.append(tr);
  }

  // 4. examples
  const box = document.getElementById("examples");
  for (const ex of examples) {
    const card = document.createElement("article");
    card.className = "example";
    const claim = document.createElement("blockquote");
    claim.textContent = ex.claim;
    const meta = document.createElement("p");
    meta.className = "meta";
    const citing = document.createElement("a");
    citing.href = `https://arxiv.org/abs/${ex.citing.arxiv_id}`; citing.textContent = ex.citing.title;
    const cited = document.createElement("a");
    cited.href = `https://arxiv.org/abs/${ex.cited.arxiv_id}`; cited.textContent = ex.cited.title;
    meta.append("From ", citing, ", citing ", cited, ".");
    const reads = document.createElement("details");
    reads.className = "reads";
    const readsSummary = document.createElement("summary");
    readsSummary.textContent = "What the full-text readers found";
    reads.append(readsSummary);
    for (const [model, r] of Object.entries(ex.reads)) {
      const p = document.createElement("p");
      p.style.margin = "0";
      const who = document.createElement("strong");
      who.textContent = `${shortName(model)} (full text): ${r.verdict.replaceAll("_", " ")}. `;
      p.append(who, document.createTextNode(r.rationale));
      if (r.quote) {
        const q = document.createElement("q");
        q.textContent = r.quote;
        p.append(document.createTextNode(` The paper says, on page ${r.page}: `), q);
      }
      reads.append(p);
    }
    card.append(claim, meta, reads);
    box.append(card);
  }
  // 5. where models fail: misses vs false alarms
  const errBody = document.querySelector("#error-table tbody");
  const byFalseAlarms = [...models].sort((a, b) => a.error_profile.arxiv.false_alarm_rate - b.error_profile.arxiv.false_alarm_rate);
  for (const m of byFalseAlarms) {
    const tr = document.createElement("tr");
    const name = document.createElement("td");
    const sw = document.createElement("span"); sw.className = "swatch"; sw.style.background = color(m.model);
    name.append(sw, document.createTextNode(shortName(m)));
    tr.append(name);
    for (const d of ["arxiv", "scifact"]) {
      const e = m.error_profile[d];
      for (const [n, total, rate] of [[e.missed, e.wrong_citations, e.miss_rate], [e.false_alarms, e.correct_citations, e.false_alarm_rate]]) {
        const td = document.createElement("td"); td.className = "num";
        td.textContent = `${fmt.int(n)} of ${fmt.int(total)} (${fmt.pct(rate)})`;
        tr.append(td);
      }
    }
    errBody.append(tr);
  }

  // 6. the hardest cases: every model wrong
  const order = [...models].sort((a, b) => a.cost_per_1000_usd - b.cost_per_1000_usd).map((m) => m.model);
  const hardBody = document.querySelector("#hard-table tbody");
  for (const h of results.hard_cases.shown) {
    const tr = document.createElement("tr");
    const claim = document.createElement("td");
    claim.className = "claim-cell";
    claim.append(document.createTextNode(h.claim));
    const src = document.createElement("span"); src.className = "sub";
    if (h.dataset === "arxiv") {
      const a = document.createElement("a"); a.href = `https://arxiv.org/abs/${h.paper_id}`; a.textContent = "citing paper";
      const b = document.createElement("a"); b.href = `https://arxiv.org/abs/${h.cited_arxiv_id}`; b.textContent = h.cited_title;
      src.append("Machine learning · ", a, " cites ", b, h.item_id.endsWith("/swapped") ? " (swapped in)" : "");
    } else {
      src.append(`Biomedical · cited abstract: ${h.cited_title}`);
    }
    const why = document.createElement("details");
    const sum = document.createElement("summary"); sum.textContent = "Why the models said so";
    why.append(sum);
    for (const id of order) {
      const v = h.verdicts[id]; if (!v) continue;
      const p = document.createElement("p"); p.className = "why";
      const who = document.createElement("strong"); who.textContent = `${shortName(id)}: `;
      p.append(who, document.createTextNode(v.rationale));
      why.append(p);
    }
    claim.append(src, why);
    tr.append(claim);
    const gold = document.createElement("td"); gold.textContent = fmt.label(h.label); tr.append(gold);
    // group identical verdicts: "🔴 Haiku, Flash: supported"
    const groups = {};
    for (const id of order) {
      const v = h.verdicts[id]; if (!v) continue;
      (groups[`${v.correct}|${v.verdict}`] ||= { correct: v.correct, verdict: v.verdict, models: [] }).models.push(shortName(id));
    }
    const said = document.createElement("td"); said.className = "verdict";
    for (const g of Object.values(groups)) {
      const line = document.createElement("div");
      const mark = document.createElement("span"); mark.textContent = g.correct ? "🟢 " : "🔴 ";
      mark.setAttribute("aria-label", g.correct ? "right:" : "wrong:");
      const who = g.models.length === order.length ? "All four" : g.models.join(", ");
      line.append(mark, document.createTextNode(`${who}: ${fmt.label(g.verdict)}`));
      said.append(line);
    }
    tr.append(said);
    hardBody.append(tr);
  }

  // 7. does paying more save editor time? (same formula as report.cost_per_paper in Python)
  const citations = results.datasets.arxiv.citations_per_paper_median;
  const minutesEl = document.getElementById("minutes"), rateEl = document.getElementById("rate");
  minutesEl.value = results.assumptions.minutes_per_flag;
  rateEl.value = results.assumptions.editor_usd_per_hour;
  const costPerPaper = (m, dataset, minutes, rate) => {
    const falseAlarms = m.error_profile[dataset].false_alarm_rate * citations;
    const editorMinutes = falseAlarms * minutes;
    const editorUsd = editorMinutes / 60 * rate;
    return { model: m, falseAlarms, editorMinutes, editorUsd, total: m.cost_per_manuscript_usd + editorUsd };
  };
  function renderCalc() {
    const dataset = document.querySelector("input[name=dataset]:checked").value;
    const minutes = +minutesEl.value, rate = +rateEl.value;
    document.getElementById("minutes-out").textContent = `${minutes} min`;
    document.getElementById("rate-out").textContent = `$${rate}`;
    const rowsC = models.map((m) => costPerPaper(m, dataset, minutes, rate)).sort((a, b) => a.total - b.total);
    const max = Math.max(...rowsC.map((r) => r.total));
    const bars = document.getElementById("bars");
    bars.replaceChildren();
    rowsC.forEach((r, i) => {
      const row = document.createElement("div"); row.className = "bar-row" + (i === 0 ? " best" : "");
      const label = document.createElement("span"); label.className = "bar-label"; label.textContent = shortName(r.model);
      const track = document.createElement("span"); track.className = "bar-track";
      const fill = document.createElement("span"); fill.className = "bar-fill";
      fill.style.width = `${Math.max(1, (r.total / max) * 100)}%`; fill.style.background = color(r.model.model);
      track.append(fill);
      const value = document.createElement("span"); value.className = "bar-value";
      value.textContent = `${fmt.usd(r.total)} per paper`;
      const detail = document.createElement("span"); detail.className = "bar-detail";
      detail.textContent = `model ${fmt.usd(r.model.cost_per_manuscript_usd)} + editor ${fmt.usd(r.editorUsd)} ` +
        `(${r.falseAlarms.toFixed(1)} false alarms, ${r.editorMinutes.toFixed(1)} min)`;
      row.append(label, track, value, detail);
      bars.append(row);
    });
    const best = rowsC[0];
    const cheapest = [...rowsC].sort((a, b) => a.model.cost_per_manuscript_usd - b.model.cost_per_manuscript_usd)[0];
    let text = `With these settings, ${shortName(best.model)} costs least overall: ${fmt.usd(best.total)} per paper.`;
    if (best !== cheapest) {
      const saved = cheapest.editorMinutes - best.editorMinutes;
      const breakEven = (best.model.cost_per_manuscript_usd - cheapest.model.cost_per_manuscript_usd) /
        ((cheapest.falseAlarms - best.falseAlarms) * rate / 60);
      text += ` It costs more to run than ${shortName(cheapest.model)}, but saves ${saved.toFixed(1)} editor minutes per ` +
        `paper; that pays off once a flag takes more than ${Math.max(1, Math.round(breakEven * 60))} seconds.`;
    } else {
      text += " It is also the cheapest to run, so paying more does not save anything here.";
    }
    document.getElementById("calc-summary").textContent = text;
    return rowsC;
  }
  document.getElementById("calc").addEventListener("input", renderCalc);
  // defaults, exposed for the automated check against docs/data/results.json
  window.__economicsDefault = Object.fromEntries(["scifact", "arxiv"].map((d) => [d, Object.fromEntries(
    models.map((m) => { const r = costPerPaper(m, d, results.assumptions.minutes_per_flag, results.assumptions.editor_usd_per_hour);
      return [m.model, r.total]; }))]));
  renderCalc();

  window.__storyReady = true;  // for the automated page check
})();
