type AlertState = {level: string; confidence: number; category: string | null; updated_at: string; evidence_count: number; independent_family_count: number; latency_seconds: Record<string, number | null>};
type Incident = {id: string; level: string; category: string; confidence: number};
type Source = {source_id: string; health: string; signal_type: string; healthy: boolean; enabled: boolean; response_latency_seconds: number | null; error: string | null};
type Status = {status: string; mode: string; updated_at: string; healthy_collectors: number; total_collectors: number; active_source_families: number; critical_available: boolean; coverage: string; warnings: string[]; deliveries: Record<string, number>};
const element = (id: string): HTMLElement => document.getElementById(id)!;
let token = "";
let cursor = "0";
let controller = new AbortController();
let refreshing = false;
const headers = (): Record<string,string> => token ? {Authorization: `Bearer ${token}`} : {};

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`/api/v1/${path}`, {headers: headers(), signal: controller.signal});
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json() as Promise<T>;
}

async function refresh(): Promise<void> {
  if (refreshing) return;
  refreshing = true;
  try {
    const [alert, incidents, sources, status] = await Promise.all([
      get<AlertState>("alert"), get<Incident[]>("incidents?active=true"), get<Source[]>("sources"), get<Status>("status")
    ]);
    element("connection").textContent = status.status === "running" ? "API 연결됨 · Core 실행 중" : "API 연결됨 · Core 응답 지연";
    document.body.dataset.running = String(status.status === "running");
    element("mode").textContent = status.status !== "running" ? "CORE STALE" : status.mode === "live" ? "LIVE PUBLIC DATA" : "SYNTHETIC · NOT LIVE";
    element("collector-count").textContent = `${status.healthy_collectors} / ${status.total_collectors}`;
    element("family-count").textContent = String(status.active_source_families);
    element("incident-count").textContent = String(incidents.length);
    document.querySelectorAll(".scale span").forEach(item => item.classList.toggle("active", item.textContent === alert.level));
    element("coverage").textContent = status.warnings.length ? status.warnings.join(" · ") : "공개 피드 수집 중 · 게시·갱신 속도에 따라 탐지가 지연될 수 있음";
    if (status.deliveries.failed) element("coverage").textContent += ` · 알림 전송 실패 ${status.deliveries.failed}건`;
    element("level").textContent = alert.level;
    element("level").dataset.level = alert.level;
    element("summary").textContent = `${alert.category ?? "활성 사건 없음"} · 신뢰도 ${Math.round(alert.confidence * 100)}% · 근거 ${alert.evidence_count} / 독립 계열 ${alert.independent_family_count} · 처리 지연 ${alert.latency_seconds?.decision == null ? "미측정" : `${alert.latency_seconds.decision.toFixed(3)}초`} · 종단 지연 미측정`;
    element("heartbeat").textContent = `${status.mode === "live" ? "실제 수집" : "합성 데이터"} · Core 확인 ${new Date(status.updated_at).toLocaleString("ko-KR")}`;
    element("source-summary").textContent = `${status.healthy_collectors} / ${status.total_collectors} 활성 소스 정상 · 검증 계열 ${status.active_source_families} · 현재 CRITICAL 필요조건 ${status.critical_available ? "충족" : "미충족"}`;
    element("incidents").replaceChildren();
    if (!incidents.length) element("incidents").textContent = "관측된 활성 사건 없음";
    for (const incident of incidents) {
      const row = document.createElement("div"); row.className = "row";
      const button = document.createElement("button");
      button.textContent = `${incident.level} · ${incident.category} · ${Math.round(incident.confidence * 100)}%`;
      button.onclick = () => { void get(`incidents/${incident.id}`).then(value => {
        element("detail").textContent = JSON.stringify(value, null, 2);
      }).catch(() => { element("detail").textContent = "상세 조회 실패"; }); };
      row.append(button); element("incidents").append(row);
    }
    element("sources").replaceChildren();
    for (const source of sources) {
      const row = document.createElement("div"); row.className = "source-row";
      const name = document.createElement("span"); name.className = "source-name"; name.textContent = source.source_id;
      const signal = document.createElement("small"); signal.textContent = source.signal_type; name.append(signal);
      const health = document.createElement("span"); health.className = "health"; health.dataset.health = source.health; health.textContent = !source.enabled ? "DISABLED" : source.health;
      const rtt = document.createElement("span"); rtt.className = "rtt"; rtt.textContent = source.response_latency_seconds == null ? "—" : `${source.response_latency_seconds.toFixed(2)} s`;
      if (source.error) row.title = source.error;
      row.append(name, health, rtt);
      element("sources").append(row);
    }
  } catch {
    document.body.dataset.running = "false";
    element("mode").textContent = "CONNECTION LOST";
    element("connection").textContent = "연결 끊김 · 표시된 상태는 최신이 아닐 수 있음";
  } finally { refreshing = false; }
}

async function stream(signal: AbortSignal): Promise<void> {
  while (!signal.aborted) {
    try {
      const response = await fetch("/api/v1/stream", {headers: {...headers(), "Last-Event-ID": cursor}, signal});
      if (!response.ok || !response.body) throw new Error("stream unavailable");
      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = "";
      while (!signal.aborted) {
        const {done, value} = await reader.read();
        if (done) break;
        buffer += value;
        let boundary: number;
        while ((boundary = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
          const lines = frame.split("\n");
          const id = lines.find(line => line.startsWith("id: "));
          if (id) cursor = id.slice(4);
          const event = lines.find(line => line.startsWith("event: "));
          if (event) {
            const row = document.createElement("li");
            row.textContent = `${new Date().toLocaleTimeString("ko-KR")} · ${event.slice(7)} · #${cursor}`;
            element("events").prepend(row);
            while (element("events").children.length > 100) element("events").lastChild?.remove();
            void refresh();
          }
        }
      }
    } catch { if (!signal.aborted) element("connection").textContent = "실시간 연결 재시도 중"; }
    if (!signal.aborted) await new Promise(resolve => setTimeout(resolve, 2000));
  }
}

element("auth").addEventListener("submit", event => {
  event.preventDefault();
  if (location.protocol !== "https:" && !["localhost", "127.0.0.1", "[::1]"].includes(location.hostname)) {
    element("connection").textContent = "외부 인증 연결에는 HTTPS가 필요함";
    return;
  }
  controller.abort(); controller = new AbortController();
  token = (element("token") as HTMLInputElement).value;
  void refresh(); void stream(controller.signal);
});
void refresh(); void stream(controller.signal);
setInterval(() => { void refresh(); }, 5000);
const clock = (): void => { element("clock").textContent = new Date().toISOString().replace("T", " ").slice(0, 19) + " UTC"; };
clock(); setInterval(clock, 1000);
