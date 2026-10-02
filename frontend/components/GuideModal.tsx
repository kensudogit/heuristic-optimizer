"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface Step {
  no: string;
  title: string;
  body: string;
  note?: string;
}

const BASIC_STEPS: Step[] = [
  {
    no: "01",
    title: "アプリを起動する",
    body: "リポジトリ直下で start.cmd（コマンドプロンプト）または .\\start.ps1（PowerShell）を実行します。中身は COMPOSE_BAKE=false 付きの docker compose up --build -d です。既定の画面は http://localhost:3010、API は http://localhost:8010/docs です。8000 / 3000 は他システム用に空けてあり、この PoC は 8010 / 3010 に出します。",
    note: "Docker Desktop が起動していることを確認してください。停止は docker compose down です。画面からの API は /api 経由なので、ブラウザは 3010 だけ開けば動きます。",
  },
  {
    no: "02",
    title: "サンプル工場を確認する",
    body: "画面を開くと、組立工場のサンプルが自動で入ります。敷地は 10 行（南北）× 12 列（東西）、中央 2×2 は通路、出荷場は南側固定です。工程チェーンは 受入 → 機械加工 → 組立 → 検査 → 出荷 です。まずは値を変えずに「レイアウト探索」を押し、動きを確認してください。",
    note: "サンプル取得に失敗しても画面の初期値で探索できます。API が落ちているときは「APIに接続できません」と出ます。",
  },
  {
    no: "03",
    title: "敷地と探索条件を決める",
    body: "行・列は敷地のセル数です。seed を入れると同じ乱数系列でヒューリスティックを再現できます。最大改善周回は局所探索の回数、提案数は返す案の上限（1〜8）、制限時間は厳密探索の打ち切り秒数です。厳密最適にチェックがあると分枝限定で最適解を証明し、外すと貪欲＋複数スタート＋焼きなましだけを使います。",
    note: "厳密モードはサンプル規模で十数秒かかることがあります。制限時間（既定 45 秒、上限 120 秒）を超えると、最適とは書かず「未証明の最良解」を返します。",
  },
  {
    no: "04",
    title: "工程・建屋を入力する",
    body: "各行は工程ID、名称、役割、幅、高さです。役割は入庫 / 製造 / 出庫 / 付帯です。工程チェーン上の棟は北から南へ進むほど費用が良くなります。固定座標を持つ棟（サンプルの出荷場）は探索中も動きません。幅と高さはセル単位の矩形です。",
    note: "工程IDは物流・隣接・チェーンから参照されます。空や重複はエラーです。敷地より大きい建屋も置けません。",
  },
  {
    no: "05",
    title: "物流と関係制約を確認する",
    body: "物流は from → to のパレット相当／日です。費用は「物流量 × 重心間マンハッタン距離」です。隣接希望は辺を共有しないとペナルティ、離隔必須は指定セル数未満だと実行不能です。サンプルでは受入—加工・検査—出荷が隣接希望、危険物庫と事務所は 3 セル以上離れます。",
    note: "通路（禁止セル）には建屋を置けません。距離は通路を避けた実走路ではなく、セル上のマンハッタンです。",
  },
  {
    no: "06",
    title: "レイアウト探索を実行する",
    body: "「レイアウト探索」を押すと API の POST /optimize が走ります。厳密モードでは分枝限定が目的関数を最小化し、探索し切れたときだけ見出しに「最適解」と出ます。ヒューリスティックでは複数案を出し、流れが整列している案を先に並べます。",
    note: "目的関数は 物流費用 + 隣接未達ペナルティ + 工程逆行ペナルティ です。ハード制約（敷地外・重複・禁止セル・離隔）を満たさない配置は返しません。",
  },
];

const ADVANCED_STEPS: Step[] = [
  {
    no: "07",
    title: "結果の数字を読む",
    body: "初期費用は貪欲法の配置、案の費用は選んだ案の総費用です。「流れ」は入庫→出庫が北から南かです。厳密最適のときはギャップ 0 です。ヒューリスティックのときは物流下界（2棟だけの最短。他棟競合は無視）との推定ギャップ、隣接達成数、整列案数、敷地利用率が出ます。",
    note: "下界は理論上の下限であり、厳密最適との差ではありません。最適と書いてあるときだけ、同じ目的関数での最小を証明しています。",
  },
  {
    no: "08",
    title: "グリッドと工程パスを見る",
    body: "左が初期解、右が選んだ案です。色は工程、×は通路です。案側には入庫（緑）から出庫（赤）までの工程パスが重なります。案ボタンを切り替えると、理由文・パス・費用内訳が一緒に変わります。",
    note: "理由文は初期解と比べて、どの物流が短くなったか、隣接できたか、南方向に整列したかを工程名で書きます。",
  },
  {
    no: "09",
    title: "お客様データに差し替える",
    body: "建屋寸法、物流OD、固定設備、禁止セル、離隔を現場の数字に置き換えて再実行します。seed を固定するとヒューリスティックの再現が取れます。厳密モードは規模が大きくなると時間切れになりやすいので、まずはヒューリスティックで案を出し、小規模だけ厳密で裏取りしてください。",
    note: "通路形状の凹凸、階数、ユーティリティ容量、法令チェックは未実装です。数字はセル単位の相対距離です。",
  },
];

const TIPS: { title: string; body: string }[] = [
  {
    title: "「最適解」と「ヒューリスティック案」を混同しない",
    body: "見出しに「厳密最適」と出たときだけ証明済みです。案1が整列していても、厳密チェックがオフなら近似解です。",
  },
  {
    title: "ポートが使えない・cmd から起動できない・Railway が失敗する",
    body: "コマンドプロンプトからは start.cmd を使います。.ps1 を直接叩いても動きません。3010 / 8010 が埋まっているときは FRONTEND_PORT / BACKEND_PORT を付けて docker compose を起動します。Railway はリポジトリ直下を Railpack で判定できないので、ルートの Dockerfile（railway.toml）でデプロイします。",
  },
  {
    title: "探索が長い・失敗する",
    body: "厳密モードは 45 秒まで待ってください。置けない寸法や離隔を満たせない入力は 400 で「実行可能解なし」になります。工程IDの空・重複は画面側でも弾きます。",
  },
  {
    title: "物流は短いが逆行と出る",
    body: "表示順は工程流れを優先します。搬送だけ短い案が残ることがありますが、入庫→出庫が南へ進まない配置です。顧客説明では「条件を満たす候補」と伝えてください。",
  },
];

const TAGS = [
  "Python 3.12",
  "FastAPI",
  "Next.js 15",
  "React 19",
  "TypeScript",
  "Docker",
  "分枝限定",
  "貪欲 + SA",
];

export function GuideModal({ onClose }: { onClose: () => void }) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const [atBottom, setAtBottom] = useState(false);

  const handleScroll = useCallback(() => {
    const element = bodyRef.current;
    if (!element) return;
    setAtBottom(element.scrollTop + element.clientHeight >= element.scrollHeight - 24);
  }, []);

  useEffect(() => {
    closeRef.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose]);

  return (
    <div className="guide-overlay" onClick={onClose} role="presentation">
      <div
        className="guide-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="guide-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="guide-header">
          <span className="guide-bar" aria-hidden="true" />
          <span className="guide-menu" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          <div className="guide-heading">
            <h2 id="guide-title">利用手順</h2>
            <p className="guide-eyebrow">FACTORY LAYOUT GUIDE</p>
          </div>
          <span className="guide-spacer" />
          {!atBottom && <span className="guide-scroll-hint">スクロールして確認</span>}
          <button
            ref={closeRef}
            type="button"
            className="guide-close"
            onClick={onClose}
            aria-label="閉じる"
          >
            ×
          </button>
        </header>

        <div className="guide-body" ref={bodyRef} onScroll={handleScroll}>
          <section className="guide-card guide-card-hero">
            <p className="guide-card-eyebrow">建設業 / 工場建設 / 施設配置</p>
            <h3>工場建設レイアウト最適化 PoC</h3>
            <p className="guide-card-text">
              敷地グリッド上に建屋を重ねずに置き、入庫→製造→出庫の流れと離隔・隣接を満たす配置を求めます。
              厳密モードでは分枝限定が最適性を証明した解だけを「最適解」と表示します。ヒューリスティックでは
              複数の実行可能案を出し、どの物流が短くなったかを文章で説明します。
            </p>
            <div className="guide-tags">
              {TAGS.map((tag) => (
                <span key={tag} className="guide-tag">
                  {tag}
                </span>
              ))}
            </div>
          </section>

          <section className="guide-card guide-card-arch">
            <div className="guide-badge-row">
              <span className="guide-badge">ARCHITECTURE</span>
              <h3>Next.js UI + FastAPI 探索エンジン</h3>
            </div>
            <p className="guide-card-text">
              ブラウザは 3010 だけ見れば動きます。画面からの API 呼び出しはコンテナ内で /api が
              バックエンドへ中継します。探索ロジックは services/optimizer.py と services/exact.py に閉じ、
              FastAPI のルートには埋め込みません。
            </p>
            <ul className="guide-list">
              <li>Next.js — 敷地・工程・物流の入力、案の切替、グリッドと工程パス</li>
              <li>FastAPI — /sample /optimize /health。CORS は 3000 と 3010</li>
              <li>分枝限定 — 同じ目的関数の厳密最適。証明できたときだけ optimal=true</li>
              <li>貪欲 + 複数スタート + 交換/SA — 厳密が重いときの近似と複数案</li>
              <li>Docker Compose — backend 8010、frontend 3010</li>
            </ul>
          </section>

          <p className="guide-section-label">BASIC WORKFLOW</p>
          {BASIC_STEPS.map((step) => (
            <StepCard key={step.no} step={step} />
          ))}

          <p className="guide-section-label">ADVANCED</p>
          {ADVANCED_STEPS.map((step) => (
            <StepCard key={step.no} step={step} />
          ))}

          <p className="guide-section-label">PRINCIPLES</p>
          <section className="guide-card guide-card-arch">
            <div className="guide-badge-row">
              <span className="guide-badge">RULES</span>
              <h3>この PoC が守っていること</h3>
            </div>
            <ul className="guide-list">
              <li>証明していない解を「最適」と呼ばない</li>
              <li>ハード制約を破る配置は返さない</li>
              <li>探索本体を API ルートに埋め込まない</li>
              <li>乱数を使うヒューリスティックは seed で再現する</li>
              <li>下界や推定ギャップを、厳密ギャップであるかのように書かない</li>
              <li>サンプル工場の証明済み最適値は 878（目的関数）</li>
            </ul>
          </section>

          <p className="guide-section-label">TIPS</p>
          <section className="guide-card">
            <dl className="guide-faq">
              {TIPS.map((tip) => (
                <div key={tip.title}>
                  <dt>{tip.title}</dt>
                  <dd>{tip.body}</dd>
                </div>
              ))}
            </dl>
          </section>

          <p className="guide-footnote">
            詳細は <code>README.md</code> と <code>docs/顧客向け検証報告.md</code> を参照してください。
          </p>
        </div>
      </div>
    </div>
  );
}

function StepCard({ step }: { step: Step }) {
  return (
    <section className="guide-step">
      <span className="guide-step-no" aria-hidden="true">
        {step.no}
      </span>
      <div className="guide-step-main">
        <h3>{step.title}</h3>
        <p>{step.body}</p>
        {step.note && <p className="guide-note">{step.note}</p>}
      </div>
    </section>
  );
}

export function GuideButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className="guide-trigger" onClick={() => setOpen(true)}>
        利用手順
      </button>
      {open && <GuideModal onClose={() => setOpen(false)} />}
    </>
  );
}
