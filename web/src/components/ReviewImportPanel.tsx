import { ArrowSquareOut, CheckCircle, FileCsv, Key, UploadSimple, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import {
  commitReviewImport,
  detectReviewImport,
  fetchImportConfig,
  previewReviewImport,
  waitForRun,
} from "../api/client";
import type { ImportConfigResponse, ReviewImportProfile, RunResponse } from "../api/types";

const PROFILE_LABELS: Record<ReviewImportProfile, string> = {
  guardian_ecommerce: "Guardian e-commerce",
  tiktok_shop: "TikTok Shop",
  shopee: "Shopee",
  lazada: "Lazada",
  grabmart: "GrabMart",
};

interface ReviewImportPanelProps {
  onImported: () => void | Promise<void>;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The import could not be completed.";
}

function importTime(value: string | null | undefined): string {
  if (!value) return "Never";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export function ReviewImportPanel({ onImported }: ReviewImportPanelProps) {
  const [config, setConfig] = useState<ImportConfigResponse | null>(null);
  const [configError, setConfigError] = useState("");
  const [configAttempt, setConfigAttempt] = useState(0);
  const [profile, setProfile] = useState<ReviewImportProfile | "">("");
  const [file, setFile] = useState<File | null>(null);
  const [token, setToken] = useState("");
  const [run, setRun] = useState<RunResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<"checking" | "importing" | "finishing" | null>(null);
  const activeRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setConfigError("");
    fetchImportConfig(controller.signal)
      .then((value) => {
        setConfig(value);
        setProfile((current) => current || value.profiles[0] || "");
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setConfigError(errorMessage(cause));
      });
    return () => controller.abort();
  }, [configAttempt]);

  useEffect(() => () => {
    activeRequest.current?.abort();
    activeRequest.current = null;
  }, []);

  const resetResult = () => {
    setRun(null);
    setError("");
  };

  const validate = (): { file: File; profile: ReviewImportProfile; token: string } | null => {
    if (!file) {
      setError("Choose a CSV or XLSX review export.");
      return null;
    }
    if (!/\.(csv|xlsx)$/i.test(file.name)) {
      setError("This file must be CSV or XLSX.");
      return null;
    }
    if (config?.max_bytes && file.size > config.max_bytes) {
      setError(`This file exceeds the ${(config.max_bytes / 1_000_000).toFixed(1)} MB limit.`);
      return null;
    }
    if (!profile) {
      setError("Choose where this export came from.");
      return null;
    }
    if (!token.trim()) {
      setError("Enter the admin access key.");
      return null;
    }
    return { file, profile, token: token.trim() };
  };

  const finishRun = async (result: RunResponse) => {
    setRun(result);
    if (result.status === "failed") {
      setError(result.error_summary || "The import failed.");
      return;
    }
    if (result.status === "completed") {
      setToken("");
      await onImported();
      return;
    }
    if (result.status === "partial") await onImported();
  };

  const pollRun = async (runId: string, controller: AbortController) => {
    setBusy("finishing");
    const terminal = await waitForRun(runId, {
      signal: controller.signal,
      onUpdate: (update) => setRun(update),
    });
    await finishRun(terminal);
  };

  const handleImport = async () => {
    const input = validate();
    if (!input) return;
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setError("");
    setRun(null);
    setBusy("checking");
    try {
      const preview = config?.agentic_detection_enabled
        ? await detectReviewImport(input.file, input.profile, input.token, controller.signal)
        : await previewReviewImport(input.file, input.profile, input.token, controller.signal);
      if (preview.duplicate_file) {
        setError("This exact file was already imported. Choose a newer export.");
        return;
      }
      if (preview.valid_rows < 1) {
        setError(preview.issues[0]?.message || "No valid reviews were found in this file.");
        return;
      }

      setBusy("importing");
      const queued = preview.mapping
        ? await commitReviewImport(input.file, input.profile, input.token, controller.signal, preview.mapping)
        : await commitReviewImport(input.file, input.profile, input.token, controller.signal);
      setRun(queued);
      if (queued.status === "queued" || queued.status === "running") {
        await pollRun(queued.pipeline_run_id, controller);
      } else {
        await finishRun(queued);
      }
    } catch (cause) {
      if (!controller.signal.aborted) setError(errorMessage(cause));
    } finally {
      if (activeRequest.current === controller) {
        activeRequest.current = null;
        setBusy(null);
      }
    }
  };

  const buttonLabel = busy === "checking"
    ? "Checking file…"
    : busy === "importing"
      ? "Importing reviews…"
      : busy === "finishing"
        ? "Finishing import…"
        : "Import reviews";

  if (!config && !configError) {
    return <section className="review-import-card" id="review-import"><p className="import-loading" role="status">Loading importer…</p></section>;
  }

  if (configError) {
    return <section className="review-import-card" id="review-import">
      <div className="import-message import-error" role="alert">
        <WarningCircle size={18} /><strong>Importer unavailable</strong><span>{configError}</span>
        <button type="button" onClick={() => setConfigAttempt((value) => value + 1)}>Retry</button>
      </div>
    </section>;
  }

  if (!config?.enabled) {
    return <section className="review-import-card" id="review-import"><div className="import-message import-warning">Review imports are disabled.</div></section>;
  }

  const sellerUrl = profile ? (config.seller_urls ?? {})[profile] : undefined;
  const locked = busy !== null;

  return (
    <section className="review-import-card" id="review-import" aria-labelledby="review-import-title">
      <div className="import-card-head">
        <div className="import-card-title">
          <span className="review-import-panel__icon"><UploadSimple size={20} weight="bold" /></span>
          <span><h3 id="review-import-title">Import reviews</h3><p>Choose the source and upload its export. Guardian handles the format.</p></span>
        </div>
        <span className="import-last-run"><b>Last import</b>{importTime(run?.completed_at ?? config.last_import_at)}</span>
      </div>

      <div className="simple-import-grid">
        <label className="simple-import-field">
          <span>Marketplace</span>
          <select
            aria-label="Source profile"
            value={profile}
            disabled={locked}
            onChange={(event) => { setProfile(event.target.value as ReviewImportProfile); resetResult(); }}
          >
            {config.profiles.map((value) => <option key={value} value={value}>{PROFILE_LABELS[value]}</option>)}
          </select>
        </label>

        <label className={`simple-file-picker ${file ? "has-file" : ""}`}>
          <FileCsv size={24} weight={file ? "fill" : "regular"} />
          <span><b>{file?.name || "Choose CSV or XLSX file"}</b><small>{file ? `${(file.size / 1_000).toFixed(0)} KB · Ready to import` : "Click to browse your computer"}</small></span>
          <input
            aria-label="CSV review export"
            type="file"
            accept={config.accepted_extensions.join(",") || ".csv,.xlsx"}
            disabled={locked}
            onChange={(event) => { setFile(event.target.files?.[0] ?? null); resetResult(); }}
          />
        </label>
      </div>

      <div className="simple-import-footer">
        <div className="simple-access-key">
          <Key size={16} />
          <input
            aria-label="Admin token"
            type="password"
            autoComplete="off"
            value={token}
            disabled={locked}
            onChange={(event) => { setToken(event.target.value); resetResult(); }}
            placeholder="Admin access key"
          />
        </div>
        {sellerUrl && <a className="seller-center-link" href={sellerUrl} target="_blank" rel="noreferrer">Get export from {PROFILE_LABELS[profile as ReviewImportProfile]} <ArrowSquareOut size={14} /></a>}
        <button className="primary-button simple-import-submit" type="button" disabled={locked || !file || !token.trim()} onClick={handleImport}>
          {buttonLabel}
        </button>
      </div>

      {config.agentic_detection_enabled === false && <p className="simple-import-note">Automatic format detection is unavailable; known marketplace columns will still be imported.</p>}
      {busy && <div className="simple-import-progress" role="status"><i /><span>{buttonLabel}</span></div>}
      {run?.status === "completed" && <div className="import-message import-success" role="status">
        <CheckCircle size={19} weight="fill" /><strong>Import complete</strong>
        <span>{run.records_inserted.toLocaleString()} new reviews · {run.records_skipped.toLocaleString()} already known · {run.records_failed.toLocaleString()} failed</span>
      </div>}
      {run?.status === "partial" && <div className="import-message import-warning" role="status">
        <WarningCircle size={19} /><strong>Some reviews could not be imported</strong>
        <span>{run.records_inserted.toLocaleString()} imported · {run.records_failed.toLocaleString()} failed</span>
      </div>}
      {error && <div className="import-message import-error" role="alert"><WarningCircle size={18} /><span>{error}</span></div>}
    </section>
  );
}
