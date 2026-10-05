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
    const reads = document.createElement("div");
    reads.className = "reads";
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
  window.__storyReady = true;  // for the automated page check
})();
