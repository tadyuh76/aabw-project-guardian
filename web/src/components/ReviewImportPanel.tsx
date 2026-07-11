import { Box, Button, Flex, Heading, Spinner, Stack, Text } from "@chakra-ui/react";
import { CheckCircle, FileCsv, UploadSimple, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useRef, useState, type DragEvent } from "react";
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
  const [dragActive, setDragActive] = useState(false);
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

  const validate = (): { file: File; profile: ReviewImportProfile } | null => {
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
    return { file, profile };
  };

  const finishRun = async (result: RunResponse) => {
    setRun(result);
    if (result.status === "failed") {
      setError(result.error_summary || "The import failed.");
      return;
    }
    if (result.status === "completed") {
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
        ? await detectReviewImport(input.file, input.profile, controller.signal)
        : await previewReviewImport(input.file, input.profile, controller.signal);
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
        ? await commitReviewImport(input.file, input.profile, controller.signal, preview.mapping)
        : await commitReviewImport(input.file, input.profile, controller.signal);
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

  const handleFile = (nextFile: File | null) => {
    setFile(nextFile);
    resetResult();
  };

  const handleDrop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    setDragActive(false);
    if (locked) return;
    handleFile(event.dataTransfer.files?.[0] ?? null);
  };

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

  const locked = busy !== null;

  return (
    <Stack as="section" aria-labelledby="review-import-title" gap="7" maxW="760px" mx="auto" bg="surface" borderWidth="1px" borderColor="border" borderRadius="panel" p={{ base: "5", md: "8" }} boxShadow="0 18px 45px rgba(15, 23, 42, 0.06)">
      <Stack align="center" gap="2" textAlign="center">
        <Flex w="12" h="12" align="center" justify="center" borderRadius="control" bg="orange.100" color="orange.700">
          <UploadSimple size={24} weight="bold" />
        </Flex>
        <Heading id="review-import-title" size="xl" letterSpacing="0">Import reviews</Heading>
        <Text color="muted" fontSize="sm">Last import: {importTime(run?.completed_at ?? config.last_import_at)}</Text>
      </Stack>

      <Stack gap="3">
        <Text fontSize="sm" fontWeight="700">Marketplace</Text>
        <Flex role="radiogroup" aria-label="Marketplace" gap="2.5" wrap="wrap">
          {config.profiles.map((value) => {
            const selected = profile === value;
            return (
              <Flex
                key={value}
                as="label"
                align="center"
                gap="2.5"
                minH="44px"
                px="3.5"
                borderWidth="1px"
                borderColor={selected ? "accent" : "border"}
                borderRadius="control"
                bg={selected ? "orange.50" : "canvas"}
                color={selected ? "accent" : "ink"}
                _dark={{ bg: selected ? "#24150d" : "canvas" }}
                cursor={locked ? "not-allowed" : "pointer"}
              >
                <input
                  className="visually-hidden"
                  type="radio"
                  name="marketplace"
                  aria-label={PROFILE_LABELS[value]}
                  value={value}
                  checked={selected}
                  disabled={locked}
                  onChange={() => { setProfile(value); resetResult(); }}
                />
                <Flex w="4" h="4" align="center" justify="center" borderRadius="full" borderWidth="2px" borderColor={selected ? "accent" : "muted"} flexShrink="0">
                  {selected && <Box w="1.5" h="1.5" borderRadius="full" bg="accent" />}
                </Flex>
                <Text fontSize="sm" fontWeight="650" whiteSpace="nowrap">{PROFILE_LABELS[value]}</Text>
              </Flex>
            );
          })}
        </Flex>
      </Stack>

      <Flex
        as="label"
        position="relative"
        minH={{ base: "190px", md: "230px" }}
        px={{ base: "5", md: "8" }}
        py="8"
        direction="column"
        align="center"
        justify="center"
        gap="4"
        textAlign="center"
        borderWidth="2px"
        borderStyle="dashed"
        borderColor={dragActive || file ? "accent" : "border"}
        borderRadius="control"
        bg={dragActive || file ? "orange.50" : "canvas"}
        _dark={{ bg: dragActive || file ? "#24150d" : "canvas" }}
        cursor={locked ? "not-allowed" : "pointer"}
        onDragOver={(event) => { event.preventDefault(); if (!locked) setDragActive(true); }}
        onDragLeave={() => setDragActive(false)}
        onDrop={handleDrop}
      >
        <Flex w="16" h="16" align="center" justify="center" borderRadius="control" bg="surface" color="accent" borderWidth="1px" borderColor="border">
          <FileCsv size={34} weight={file ? "fill" : "regular"} />
        </Flex>
        <Stack gap="1" maxW="520px">
          <Heading size="md" letterSpacing="0" wordBreak="break-word">{file?.name || "Choose CSV or XLSX file"}</Heading>
          <Text color="muted" fontSize="sm">{file ? `${(file.size / 1_000).toFixed(0)} KB selected` : "Click to browse or drag the export here"}</Text>
        </Stack>
        <Box as="span" px="5" py="2.5" borderWidth="1px" borderColor="border" borderRadius="control" bg="surface" color="ink" fontWeight="700">
          Select file
        </Box>
        <input
          className="visually-hidden"
          aria-label="CSV review export"
          type="file"
          accept={config.accepted_extensions.join(",") || ".csv,.xlsx"}
          disabled={locked}
          onChange={(event) => handleFile(event.target.files?.[0] ?? null)}
        />
      </Flex>

      <Flex justify="center">
        <Button w={{ base: "full", md: "360px" }} h="54px" size="lg" colorPalette="orange" disabled={locked || !file || !profile} onClick={handleImport}>
          {busy && <Spinner size="xs" />}
          {buttonLabel}
        </Button>
      </Flex>

      {config.agentic_detection_enabled === false && <Text color="muted" fontSize="sm">Automatic detection is unavailable.</Text>}
      {busy && <Flex align="center" gap="2" color="muted" fontSize="sm" role="status"><Spinner size="xs" />{buttonLabel}</Flex>}
      {run?.status === "completed" && <Flex p="4" gap="3" borderLeftWidth="4px" borderColor="success" bg="canvas" role="status"><CheckCircle size={19} weight="fill" /><Box><Text fontWeight="700">Import complete</Text><Text color="muted" fontSize="sm">{run.records_inserted.toLocaleString()} new - {run.records_skipped.toLocaleString()} skipped - {run.records_failed.toLocaleString()} failed</Text></Box></Flex>}
      {run?.status === "partial" && <Flex p="4" gap="3" borderLeftWidth="4px" borderColor="orange.500" bg="canvas" role="status"><WarningCircle size={19} /><Box><Text fontWeight="700">Some reviews could not be imported</Text><Text color="muted" fontSize="sm">{run.records_inserted.toLocaleString()} imported - {run.records_failed.toLocaleString()} failed</Text></Box></Flex>}
      {error && <Flex p="4" gap="3" borderLeftWidth="4px" borderColor="danger" bg="canvas" role="alert"><WarningCircle size={18} /><Text>{error}</Text></Flex>}
    </Stack>
  );
}
