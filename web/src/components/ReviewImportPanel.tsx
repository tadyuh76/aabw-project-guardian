import { Box, Button, Flex, Grid, Heading, Input, Spinner, Stack, Text } from "@chakra-ui/react";
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
    ? "Checking file..."
    : busy === "importing"
      ? "Importing..."
      : busy === "finishing"
        ? "Finishing..."
        : "Import reviews";

  if (!config && !configError) {
    return <Flex minH="120px" align="center" justify="center" gap="3" role="status"><Spinner size="sm" color="accent" /><Text color="muted">Loading importer...</Text></Flex>;
  }

  if (configError) {
    return (
      <Flex p="4" gap="3" borderLeftWidth="4px" borderColor="danger" bg="surface" role="alert">
        <WarningCircle size={18} />
        <Box flex="1"><Text fontWeight="700">Importer unavailable</Text><Text color="muted">{configError}</Text></Box>
        <Button size="sm" variant="outline" onClick={() => setConfigAttempt((value) => value + 1)}>Retry</Button>
      </Flex>
    );
  }

  if (!config?.enabled) {
    return <Text color="muted">Review imports are disabled.</Text>;
  }

  const sellerUrl = profile ? (config.seller_urls ?? {})[profile] : undefined;
  const locked = busy !== null;
  const fieldStyle = { width: "full", height: "44px", px: "3", bg: "canvas", borderWidth: "1px", borderColor: "border", borderRadius: "control" } as const;

  return (
    <Stack as="section" aria-labelledby="review-import-title" gap="5" bg="surface" borderWidth="1px" borderColor="border" borderRadius="panel" p={{ base: "5", md: "6" }}>
      <Flex justify="space-between" align={{ base: "flex-start", md: "center" }} direction={{ base: "column", md: "row" }} gap="4">
        <Flex gap="3" align="center">
          <Flex w="10" h="10" align="center" justify="center" borderRadius="control" bg="orange.100" color="orange.700"><UploadSimple size={20} weight="bold" /></Flex>
          <Heading id="review-import-title" size="lg" letterSpacing="0">Import reviews</Heading>
        </Flex>
        <Text color="muted" fontSize="sm">Last import: {importTime(run?.completed_at ?? config.last_import_at)}</Text>
      </Flex>

      <Grid gridTemplateColumns={{ base: "1fr", lg: "minmax(180px, .55fr) minmax(300px, 1.45fr)" }} gap="4">
        <Box as="label">
          <Text mb="2" fontSize="sm" fontWeight="650">Marketplace</Text>
          <Box asChild {...fieldStyle}>
            <select aria-label="Source profile" value={profile} disabled={locked} onChange={(event) => { setProfile(event.target.value as ReviewImportProfile); resetResult(); }}>
              {config.profiles.map((value) => <option key={value} value={value}>{PROFILE_LABELS[value]}</option>)}
            </select>
          </Box>
        </Box>
        <Flex as="label" position="relative" minH="76px" px="4" align="center" gap="3" borderWidth="1px" borderStyle="dashed" borderColor={file ? "accent" : "border"} borderRadius="control" bg={file ? "orange.50" : "canvas"} _dark={{ bg: file ? "#24150d" : "canvas" }} cursor="pointer">
          <FileCsv size={25} weight={file ? "fill" : "regular"} />
          <Box minW="0">
            <Text fontWeight="700" truncate>{file?.name || "Choose CSV or XLSX file"}</Text>
            <Text color="muted" fontSize="sm">{file ? `${(file.size / 1_000).toFixed(0)} KB` : "Browse file"}</Text>
          </Box>
          <input className="visually-hidden" aria-label="CSV review export" type="file" accept={config.accepted_extensions.join(",") || ".csv,.xlsx"} disabled={locked} onChange={(event) => { setFile(event.target.files?.[0] ?? null); resetResult(); }} />
        </Flex>
      </Grid>

      <Flex align={{ base: "stretch", lg: "center" }} direction={{ base: "column", lg: "row" }} gap="3">
        <Flex flex="1" maxW={{ lg: "360px" }} align="center" gap="2" px="3" bg="canvas" borderWidth="1px" borderColor="border" borderRadius="control">
          <Key size={16} />
          <Input aria-label="Admin token" type="password" autoComplete="off" value={token} disabled={locked} onChange={(event) => { setToken(event.target.value); resetResult(); }} placeholder="Admin access key" border="0" outline="0" />
        </Flex>
        {sellerUrl && <Flex asChild align="center" gap="1" color="accent" fontSize="sm" fontWeight="650"><a href={sellerUrl} target="_blank" rel="noreferrer">Seller center <ArrowSquareOut size={14} /></a></Flex>}
        <Button ml={{ lg: "auto" }} colorPalette="orange" disabled={locked || !file || !token.trim()} onClick={handleImport}>{busy && <Spinner size="xs" />}{buttonLabel}</Button>
      </Flex>

      {config.agentic_detection_enabled === false && <Text color="muted" fontSize="sm">Automatic detection is unavailable.</Text>}
      {busy && <Flex align="center" gap="2" color="muted" fontSize="sm" role="status"><Spinner size="xs" />{buttonLabel}</Flex>}
      {run?.status === "completed" && <Flex p="4" gap="3" borderLeftWidth="4px" borderColor="success" bg="canvas" role="status"><CheckCircle size={19} weight="fill" /><Box><Text fontWeight="700">Import complete</Text><Text color="muted" fontSize="sm">{run.records_inserted.toLocaleString()} new - {run.records_skipped.toLocaleString()} skipped - {run.records_failed.toLocaleString()} failed</Text></Box></Flex>}
      {run?.status === "partial" && <Flex p="4" gap="3" borderLeftWidth="4px" borderColor="orange.500" bg="canvas" role="status"><WarningCircle size={19} /><Box><Text fontWeight="700">Some reviews could not be imported</Text><Text color="muted" fontSize="sm">{run.records_inserted.toLocaleString()} imported - {run.records_failed.toLocaleString()} failed</Text></Box></Flex>}
      {error && <Flex p="4" gap="3" borderLeftWidth="4px" borderColor="danger" bg="canvas" role="alert"><WarningCircle size={18} /><Text>{error}</Text></Flex>}
    </Stack>
  );
}
