(() => {
  const app = document.getElementById("app");
  const STORE_KEY = "wtt-answers";
  const PARTICIPANT_KEY = "wtt-participant";
  const RUN_KEY = "wtt-run";
  const SENT_PREFIX = "wtt-sent-";
  const byId = Object.fromEntries(CHARACTERS.map((c) => [c.id, c]));
  const ENERGY_ORDER = ["steady", "achieve", "explore"];

  let answers = loadAnswers();
  let qIndex = 0;
  let compatPair = [];
  let lastSubmit = null;

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  function loadParticipant() {
    try {
      const p = JSON.parse(localStorage.getItem(PARTICIPANT_KEY) || "null");
      return p && p.team && p.name ? p : null;
    } catch {
      return null;
    }
  }

  function newRunId() {
    if (crypto.randomUUID) return crypto.randomUUID();
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  }

  function startRun() {
    answers = [];
    qIndex = 0;
    saveAnswers();
    sessionStorage.setItem(RUN_KEY, newRunId());
    go("#/q");
  }

  function loadAnswers() {
    try {
      const saved = JSON.parse(sessionStorage.getItem(STORE_KEY) || "[]");
      return Array.isArray(saved) ? saved : [];
    } catch {
      return [];
    }
  }

  function saveAnswers() {
    sessionStorage.setItem(STORE_KEY, JSON.stringify(answers));
  }

  function go(hash) {
    if (location.hash === hash) render();
    else location.hash = hash;
  }

  function img(id) {
    return `img/${id}.png`;
  }

  function findCharacter(axes) {
    return CHARACTERS.find(
      (c) => c.axes.work === axes.work && c.axes.collab === axes.collab && c.axes.energy === axes.energy,
    );
  }

  function axisTotals() {
    return QUESTIONS.reduce(
      (acc, q) => {
        acc[q.axis] += 1;
        return acc;
      },
      { work: 0, collab: 0, energy: 0 },
    );
  }

  function lastPick(axis) {
    for (let i = QUESTIONS.length - 1; i >= 0; i -= 1) {
      if (QUESTIONS[i].axis === axis && answers[i]) return answers[i];
    }
    return "";
  }

  function pairWinner(axis, a, b) {
    const counts = scoreCounts();
    if (counts[a] === counts[b]) {
      const last = lastPick(axis);
      return last === a || last === b ? last : b;
    }
    return counts[a] > counts[b] ? a : b;
  }

  function scoreCounts() {
    const counts = { plan: 0, flex: 0, deep: 0, link: 0, steady: 0, achieve: 0, explore: 0 };
    answers.forEach((v, i) => {
      if (QUESTIONS[i] && QUESTIONS[i].options.some((o) => o.v === v)) counts[v] += 1;
    });
    return counts;
  }

  function indexOf(count, total) {
    if (!total) return 0;
    return Math.round((count / total) * 100);
  }

  function indexSummary(result) {
    const totals = axisTotals();
    return ["work", "collab", "energy"]
      .map((k) => `${AXES[k].label} ${AXES[k].poles[result.axes[k]]} ${indexOf(result.counts[result.axes[k]], totals[k])}`)
      .join(" · ");
  }

  function score() {
    const counts = scoreCounts();

    const work = pairWinner("work", "plan", "flex");
    const collab = pairWinner("collab", "deep", "link");

    const top = Math.max(...ENERGY_ORDER.map((p) => counts[p]));
    const tied = ENERGY_ORDER.filter((p) => counts[p] === top);
    const last = lastPick("energy");
    const energy = tied.length === 1 ? tied[0] : tied.includes(last) ? last : tied[0];

    const others = ENERGY_ORDER.filter((p) => p !== energy).sort((a, b) => counts[b] - counts[a]);
    const energySecond = others[0];

    return {
      axes: { work, collab, energy },
      counts,
      margins: {
        work: Math.abs(counts.plan - counts.flex),
        collab: Math.abs(counts.deep - counts.link),
        energy: counts[energy] - counts[energySecond],
      },
      energySecond,
    };
  }

  function diffAxes(a, b) {
    return ["work", "collab", "energy"].filter((k) => a.axes[k] !== b.axes[k]);
  }

  function compatKind(a, b) {
    const diff = diffAxes(a, b);
    if (diff.length === 0) return "same";
    if (diff.length === 1) return diff[0] === "energy" ? "motive" : "complement";
    if (diff.length === 2) return "tune";
    return "learn";
  }

  function flip(axis, pole, energyAlt) {
    if (axis === "work") return pole === "plan" ? "flex" : "plan";
    if (axis === "collab") return pole === "deep" ? "link" : "deep";
    return energyAlt;
  }

  function pickMatches(ch, result) {
    const margins = result ? result.margins : { work: 1, collab: 2, energy: 3 };
    const energyAlt = result ? result.energySecond : ENERGY_ORDER.find((p) => p !== ch.axes.energy);
    const order = ["work", "collab", "energy"].sort((a, b) => margins[a] - margins[b]);

    const complements = order.slice(0, 2).map((axis) => {
      const axes = { ...ch.axes, [axis]: flip(axis, ch.axes[axis], energyAlt) };
      return findCharacter(axes);
    });
    const learn = findCharacter({
      work: flip("work", ch.axes.work),
      collab: flip("collab", ch.axes.collab),
      energy: energyAlt,
    });
    return [...complements, learn];
  }

  function gifts(from, to) {
    return diffAxes(from, to).map((k) => from.axes[k]);
  }

  function objectParticle(word) {
    const code = word.charCodeAt(word.length - 1) - 0xac00;
    return code >= 0 && code % 28 !== 0 ? "을" : "를";
  }

  function giftSummary(from, to) {
    const poles = gifts(from, to);
    if (poles.length === 1) return POLE_GIFTS[poles[0]];
    const words = poles.map((p) => POLE_SHORT[p]);
    const last = words[words.length - 1];
    return `${words.join(" · ")}${objectParticle(last)} 채워 줘요`;
  }

  function giftList(from, to) {
    return gifts(from, to)
      .map((p) => `<p>${POLE_GIFTS[p]}</p>`)
      .join("");
  }

  function axisChips(ch) {
    return ["work", "collab", "energy"]
      .map((k) => `<span class="chip">${AXES[k].poles[ch.axes[k]]}</span>`)
      .join("");
  }

  // ---------- 화면 ----------

  function teamField(team) {
    if (TEAMS.length) {
      const options = TEAMS.map(
        (t) => `<option value="${escapeHtml(t)}"${t === team ? " selected" : ""}>${escapeHtml(t)}</option>`,
      ).join("");
      return `<select class="field-input picker" id="team" name="team" required>
          <option value=""${TEAMS.includes(team) ? "" : " selected"} disabled>팀을 골라 주세요</option>${options}
        </select>`;
    }
    return `<input class="field-input" id="team" name="team" maxlength="30" autocomplete="organization"
        placeholder="예: 기획팀" value="${escapeHtml(team)}" required />`;
  }

  function renderStart() {
    const preview = ["walking-checklist", "brainstorm-host", "silent-fixer", "ace-captain", "experimenter", "peacekeeper"];
    const p = loadParticipant() || { team: "", name: "" };
    app.innerHTML = `
      <main class="wrap start">
        <div class="start-collage">
          ${preview.map((id) => `<img src="${img(id)}" alt="" />`).join("")}
        </div>
        <span class="event-badge">EMO Task 워크샵</span>
        <h1 class="start-title">업무 캐릭터 테스트</h1>
        <p class="intro" id="intro">30개 질문으로 알아보는<br />EMO Task 속 나의 업무 캐릭터와 성향 지수</p>
        <form class="start-form" data-form="start" novalidate>
          <label class="field">
            <span class="field-label">팀</span>
            ${teamField(p.team)}
          </label>
          <label class="field">
            <span class="field-label">이름</span>
            <input class="field-input" id="name" name="name" maxlength="20" autocomplete="name"
              placeholder="예: 홍길동" value="${escapeHtml(p.name)}" required />
          </label>
          <p class="form-error" id="form-error" role="alert"></p>
          <div class="start-actions">
            <button class="btn btn-primary btn-block" type="submit">테스트 시작하기</button>
            <button class="btn btn-ghost btn-block" data-go="#/dex" type="button">12개 캐릭터 구경하기</button>
          </div>
          <p class="form-note">결과가 나오면 팀·이름과 함께 진행자에게 전달돼요.</p>
        </form>
      </main>`;
  }

  function submitStart(form) {
    const team = form.team.value.trim();
    const name = form.name.value.trim();
    const error = form.querySelector("#form-error");
    const missing = !team ? form.team : !name ? form.name : null;
    if (missing) {
      error.textContent = !team ? (TEAMS.length ? "팀을 골라 주세요" : "팀을 입력해 주세요") : "이름을 입력해 주세요";
      missing.focus();
      return;
    }
    localStorage.setItem(PARTICIPANT_KEY, JSON.stringify({ team, name }));
    startRun();
  }

  function renderQuestion() {
    const total = QUESTIONS.length;
    const item = QUESTIONS[qIndex];
    const selected = answers[qIndex];
    app.innerHTML = `
      <main class="wrap quiz">
        <div class="quiz-top">
          <button class="icon-btn" data-act="prev" type="button" aria-label="이전 문항">‹</button>
          <div class="progress"><span style="width:${((qIndex + 1) / total) * 100}%"></span></div>
          <span class="progress-num">${qIndex + 1}/${total}</span>
        </div>
        <div class="quiz-body fade-in">
          <p class="q-num">Q${qIndex + 1}</p>
          <h2 class="q-text">${item.q}</h2>
          <div class="options">
            ${item.options
              .map(
                (o) =>
                  `<button class="option${selected === o.v ? " is-selected" : ""}" data-pick="${o.v}" type="button">${o.t}</button>`,
              )
              .join("")}
          </div>
        </div>
      </main>`;
  }

  function renderLoading() {
    app.innerHTML = `
      <main class="wrap loading">
        <div class="spinner"></div>
        <p>나의 업무 캐릭터를 찾고 있어요</p>
      </main>`;
  }

  function ratioCard(result) {
    const { counts, axes } = result;
    const totals = axisTotals();
    const rows = [
      { key: "work", poles: ["plan", "flex"] },
      { key: "collab", poles: ["deep", "link"] },
    ].map(({ key, poles }) => {
      const total = totals[key];
      const main = axes[key];
      const other = poles.find((p) => p !== main);
      const mainIndex = indexOf(counts[main], total);
      const otherIndex = indexOf(counts[other], total);
      const gap = counts[main] - counts[other];
      const note =
        gap === 0
          ? "지수가 같아서, 이 축의 마지막 답으로 정했어요"
          : gap <= 2
            ? `${AXES[key].poles[other]} 성향도 꽤 가지고 있어요`
            : "";
      return `
        <div class="axis">
          <div class="axis-name">${AXES[key].label}</div>
          <div class="axis-head"><span class="on">${AXES[key].poles[main]} <b class="index-num">${mainIndex}</b></span><span class="off">${AXES[key].poles[other]} ${otherIndex}</span></div>
          <div class="bar"><span class="seg-main" style="width:${mainIndex}%"></span></div>
          ${note ? `<p class="axis-note">${note}</p>` : ""}
        </div>`;
    });

    const energyTotal = totals.energy;
    const energySorted = [axes.energy, ...ENERGY_ORDER.filter((p) => p !== axes.energy).sort((a, b) => counts[b] - counts[a])];
    const pcts = energySorted.map((p) => indexOf(counts[p], energyTotal));
    const energyEven = counts[energySorted[0]] === counts[energySorted[2]];
    const energyTied = counts[energySorted[0]] === counts[energySorted[1]];
    const energyClose = counts[energySorted[0]] - counts[energySorted[1]] <= 2;
    const energyNote = energyEven
      ? "세 가지 에너지가 고르게 섞여 있어요"
      : energyTied
        ? "지수가 같아서, 이 축의 마지막 답으로 정했어요"
        : energyClose
          ? `${AXES.energy.poles[energySorted[1]]} 성향도 꽤 가지고 있어요`
          : "";
    rows.push(`
      <div class="axis">
        <div class="axis-name">${AXES.energy.label}</div>
        <div class="axis-head"><span class="on">${AXES.energy.poles[energySorted[0]]} <b class="index-num">${pcts[0]}</b></span><span class="off">${AXES.energy.poles[energySorted[1]]} ${pcts[1]} · ${AXES.energy.poles[energySorted[2]]} ${pcts[2]}</span></div>
        <div class="bar">
          <span class="seg-main" style="width:${pcts[0]}%"></span>
          <span class="seg-2" style="width:${pcts[1]}%"></span>
          <span class="seg-3" style="width:${pcts[2]}%"></span>
        </div>
        ${energyNote ? `<p class="axis-note">${energyNote}</p>` : ""}
      </div>`);

    return `<section class="card"><h2>나의 성향 지수</h2><p class="index-lead">고른 답을 100점 만점으로 환산했어요. 높을수록 그쪽으로 더 기울어 있어요.</p>${rows.join("")}</section>`;
  }

  function characterBody(ch, result) {
    const matches = pickMatches(ch, result);
    return `
      <section class="hero">
        <span class="hero-label">${result ? "EMO Task 속 나의 업무 캐릭터는" : axisChips(ch)}</span>
        <img src="${img(ch.id)}" alt="${ch.name} 캐릭터" />
        <h1>${ch.name}</h1>
        <p class="one-liner">${ch.oneLiner}</p>
        <div class="tags">${ch.tags.map((t) => `<span class="tag">#${t}</span>`).join("")}</div>
      </section>

      <section class="card">
        <h2>이런 사람이에요</h2>
        <p>${ch.about}</p>
      </section>

      ${result ? ratioCard(result) : ""}

      <section class="card">
        <h2>이런 게 강점이에요</h2>
        ${ch.strengths
          .map(
            (s, i) =>
              `<div class="point good"><div class="dot">${i + 1}</div><div><strong>${s.t}</strong><span>${s.d}</span></div></div>`,
          )
          .join("")}
      </section>

      <section class="card">
        <h2>이런 건 조금 챙겨 보세요</h2>
        ${ch.cares
          .map((c) => `<div class="point care"><div class="dot">!</div><div><strong>${c.t}</strong><span>${c.d}</span></div></div>`)
          .join("")}
      </section>

      <section class="card">
        <h2>일터에서의 나</h2>
        <div class="scene"><b>일할 때</b><p>${ch.scenes.work}</p></div>
        <div class="scene"><b>회의에서</b><p>${ch.scenes.meeting}</p></div>
        <div class="scene"><b>피드백 받을 때</b><p>${ch.scenes.feedback}</p></div>
      </section>

      <section class="card">
        <h2>궁합 미리보기</h2>
        ${matches
          .map((m) => {
            const kind = COMPAT_KINDS[compatKind(ch, m)];
            return `
              <button class="match" data-go="#/compat/${ch.id}/${m.id}" type="button">
                <img src="${img(m.id)}" alt="" />
                <div>
                  <span class="badge">${kind.label}</span>
                  <strong>${m.name}</strong>
                  <span>${giftSummary(m, ch)}</span>
                </div>
              </button>`;
          })
          .join("")}
        <button class="link-btn" data-go="#/compat/${ch.id}" type="button">다른 캐릭터와 궁합 보기 ›</button>
      </section>

      <section class="card dex-teaser">
        <h2>다른 캐릭터도 궁금하다면</h2>
        <button class="btn btn-ghost btn-block" data-go="#/dex" type="button">12개 캐릭터 도감 보기</button>
      </section>`;
  }

  function renderResult() {
    answers = loadAnswers();
    if (answers.length < QUESTIONS.length) return go("#/");
    const result = score();
    const ch = findCharacter(result.axes);
    const p = loadParticipant();
    app.innerHTML = `
      <main class="wrap">
        ${
          p
            ? `<div class="submit-bar">
                <span class="who">${escapeHtml(p.team)} · ${escapeHtml(p.name)}</span>
                <span class="submit-status" id="submit-status"></span>
              </div>`
            : ""
        }
        ${characterBody(ch, result)}
      </main>
      <div class="actions"><div class="actions-inner">
        <button class="btn btn-ghost" data-act="restart" type="button">다시 하기</button>
        <button class="btn btn-primary" data-share="${ch.id}" type="button">결과 공유하기</button>
      </div></div>`;
    if (p) submitResult(p, ch, result);
  }

  function setSubmitStatus(state) {
    const el = document.getElementById("submit-status");
    if (!el) return;
    const view = {
      sending: "진행자에게 보내는 중…",
      sent: "✓ 진행자에게 전달됐어요",
      failed: `전달 실패 <button class="retry-btn" data-act="resubmit" type="button">다시 보내기</button>`,
      off: "진행자 수집 주소가 설정되지 않았어요",
    }[state];
    el.className = `submit-status is-${state}`;
    el.innerHTML = view;
  }

  async function submitResult(p, ch, result) {
    if (!SUBMIT_URL) return setSubmitStatus("off");

    let runId = sessionStorage.getItem(RUN_KEY);
    if (!runId) {
      runId = newRunId();
      sessionStorage.setItem(RUN_KEY, runId);
    }
    if (sessionStorage.getItem(SENT_PREFIX + runId)) return setSubmitStatus("sent");

    lastSubmit = () => submitResult(p, ch, result);
    setSubmitStatus("sending");
    const payload = {
      runId,
      team: p.team,
      name: p.name,
      characterId: ch.id,
      character: ch.name,
      work: AXES.work.poles[result.axes.work],
      collab: AXES.collab.poles[result.axes.collab],
      energy: AXES.energy.poles[result.axes.energy],
      index: indexSummary(result),
      answers: answers.map((v, i) => `Q${i + 1}:${v}`),
    };
    try {
      // Apps Script는 CORS 응답을 주지 않아서 no-cors로 보내고, 네트워크 오류만 실패로 본다.
      await fetch(SUBMIT_URL, {
        method: "POST",
        mode: "no-cors",
        headers: { "Content-Type": "text/plain;charset=utf-8" },
        body: JSON.stringify(payload),
        keepalive: true,
      });
      sessionStorage.setItem(SENT_PREFIX + runId, "1");
      setSubmitStatus("sent");
    } catch {
      setSubmitStatus("failed");
    }
  }

  function renderType(id) {
    const ch = byId[id];
    if (!ch) return go("#/dex");
    app.innerHTML = `
      <main class="wrap">
        <button class="back-link" data-act="back" type="button">‹ 뒤로</button>
        ${characterBody(ch, null)}
      </main>
      <div class="actions"><div class="actions-inner">
        <button class="btn btn-ghost" data-share="${ch.id}" type="button">공유하기</button>
        <button class="btn btn-primary" data-go="#/" type="button">나도 테스트하기</button>
      </div></div>`;
  }

  function renderDex() {
    const mine = answers.length === QUESTIONS.length ? findCharacter(score().axes) : null;
    app.innerHTML = `
      <main class="wrap">
        <button class="back-link" data-act="back" type="button">‹ 뒤로</button>
        <h1 class="page-title">캐릭터 도감</h1>
        <p class="page-sub">일 처리 · 협업 · 에너지 세 가지 성향 지수 조합으로 12개 캐릭터가 나와요.</p>
        <div class="dex-grid">
          ${CHARACTERS.map(
            (c) => `
              <button class="dex-card${mine && mine.id === c.id ? " is-mine" : ""}" data-go="#/type/${c.id}" type="button">
                ${mine && mine.id === c.id ? '<span class="mine-badge">나</span>' : ""}
                <img src="${img(c.id)}" alt="" loading="lazy" />
                <strong>${c.name}</strong>
                <div class="chips">${axisChips(c)}</div>
              </button>`,
          ).join("")}
        </div>
      </main>`;
  }

  function picker(name, selectedId) {
    return `
      <select class="picker" data-pick-compat="${name}">
        ${CHARACTERS.map((c) => `<option value="${c.id}"${c.id === selectedId ? " selected" : ""}>${c.name}</option>`).join("")}
      </select>`;
  }

  function renderCompat(aId, bId) {
    const mine = answers.length === QUESTIONS.length ? findCharacter(score().axes) : null;
    const a = byId[aId] || mine || CHARACTERS[0];
    const b = byId[bId] || pickMatches(a, null)[0];
    compatPair = [a.id, b.id];
    const kindKey = compatKind(a, b);
    const kind = COMPAT_KINDS[kindKey];
    const shared = ["work", "collab", "energy"].filter((k) => a.axes[k] === b.axes[k]);

    app.innerHTML = `
      <main class="wrap">
        <button class="back-link" data-act="back" type="button">‹ 뒤로</button>
        <h1 class="page-title">캐릭터 궁합 보기</h1>
        <p class="page-sub">두 캐릭터를 골라 보세요.</p>

        <section class="card compat-pick">
          <div class="compat-col">
            <img src="${img(a.id)}" alt="" />
            ${picker("a", a.id)}
          </div>
          <span class="compat-x">×</span>
          <div class="compat-col">
            <img src="${img(b.id)}" alt="" />
            ${picker("b", b.id)}
          </div>
        </section>

        <section class="card compat-result fade-in">
          <span class="badge badge-lg">${kind.label}</span>
          <h2>${kind.headline}</h2>
          ${
            shared.length
              ? `<p class="shared">같은 점 · ${shared.map((k) => AXES[k].poles[a.axes[k]]).join(" · ")}</p>`
              : ""
          }
          ${
            kindKey === "same"
              ? ""
              : `
            <div class="gift"><b>${b.name} → ${a.name}</b>${giftList(b, a)}</div>
            <div class="gift"><b>${a.name} → ${b.name}</b>${giftList(a, b)}</div>`
          }
          <p class="tip">${kind.tip}</p>
        </section>
      </main>`;
  }

  // ---------- 동작 ----------

  async function share(id) {
    const ch = byId[id];
    const url = `${location.origin}${location.pathname}#/type/${id}`;
    const text = `[EMO Task 워크샵] 나의 업무 캐릭터는 "${ch.name}"\n${ch.oneLiner}\n${ch.tags.map((t) => `#${t}`).join(" ")}`;
    if (navigator.share) {
      try {
        await navigator.share({ title: "EMO Task 업무 캐릭터 테스트", text, url });
      } catch {
        /* 사용자가 공유 창을 닫은 경우 */
      }
      return;
    }
    try {
      await navigator.clipboard.writeText(`${text}\n${url}`);
      toast("결과 링크를 복사했어요");
    } catch {
      toast("복사에 실패했어요. 주소창의 링크를 공유해 주세요");
    }
  }

  function toast(msg) {
    const el = document.createElement("div");
    el.className = "toast";
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.classList.add("show"), 10);
    setTimeout(() => {
      el.classList.remove("show");
      setTimeout(() => el.remove(), 300);
    }, 2000);
  }

  let picking = false;

  function pick(value) {
    if (picking) return;
    picking = true;
    answers[qIndex] = value;
    saveAnswers();
    renderQuestionSelected(value);
    if (qIndex < QUESTIONS.length - 1) {
      qIndex += 1;
      setTimeout(() => {
        picking = false;
        renderQuestion();
      }, 160);
    } else {
      setTimeout(() => {
        picking = false;
        renderLoading();
        setTimeout(() => go("#/result"), 1100);
      }, 160);
    }
  }

  function renderQuestionSelected(value) {
    app.querySelectorAll(".option").forEach((b) => b.classList.toggle("is-selected", b.dataset.pick === value));
  }

  app.addEventListener("click", (e) => {
    const el = e.target.closest("button");
    if (!el) return;
    if (el.dataset.pick) return pick(el.dataset.pick);
    if (el.dataset.go) return go(el.dataset.go);
    if (el.dataset.share) return share(el.dataset.share);
    const act = el.dataset.act;
    if (act === "restart") {
      if (loadParticipant()) startRun();
      else go("#/");
    } else if (act === "resubmit") {
      if (lastSubmit) lastSubmit();
    } else if (act === "prev") {
      if (qIndex === 0) go("#/");
      else {
        qIndex -= 1;
        renderQuestion();
      }
    } else if (act === "back") {
      if (history.length > 1) history.back();
      else go("#/");
    }
  });

  app.addEventListener("submit", (e) => {
    const form = e.target.closest("[data-form='start']");
    if (!form) return;
    e.preventDefault();
    submitStart(form);
  });

  app.addEventListener("input", (e) => {
    if (e.target.closest("[data-form='start']")) {
      const error = document.getElementById("form-error");
      if (error) error.textContent = "";
    }
  });

  app.addEventListener("change", (e) => {
    const sel = e.target.closest("[data-pick-compat]");
    if (!sel) return;
    const [aId, bId] = compatPair;
    const next = sel.dataset.pickCompat === "a" ? [sel.value, bId] : [aId, sel.value];
    history.replaceState(null, "", `#/compat/${next[0]}/${next[1]}`);
    render();
  });

  function render() {
    const parts = location.hash.replace(/^#\/?/, "").split("/");
    const route = parts[0];
    window.scrollTo(0, 0);
    if (route === "q") {
      if (!loadParticipant()) return go("#/");
      if (qIndex >= QUESTIONS.length) qIndex = 0;
      renderQuestion();
    } else if (route === "result") renderResult();
    else if (route === "type") renderType(parts[1]);
    else if (route === "dex") renderDex();
    else if (route === "compat") renderCompat(parts[1], parts[2]);
    else renderStart();
  }

  window.addEventListener("hashchange", render);
  render();
})();
