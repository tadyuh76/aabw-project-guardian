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
import type { ImportConfigResponse, ImportPreviewResponse, ReviewImportProfile, RunResponse } from "../api/types";

const PROFILE_LABELS: Record<ReviewImportProfile, string> = {
  guardian_ecommerce: "Guardian e-commerce",
  tiktok_shop: "TikTok Shop",
  shopee: "Shopee",
  lazada: "Lazada",
  grabmart: "GrabMart",
};

const PROFILE_LOGOS: Record<ReviewImportProfile, string> = {
  guardian_ecommerce: "/logo.svg",
  tiktok_shop: "/marketplace-logos/tiktok.svg",
  shopee: "/marketplace-logos/shopee.svg",
  lazada: "/marketplace-logos/lazada.svg",
  grabmart: "/marketplace-logos/grabmart.png",
};

const PREVIEW_COLUMNS = [
  "source_platform",
  "brand",
  "occurred_at",
  "rating",
  "product_name",
  "text",
] as const;

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

function shortColumnLabel(value: string): string {
  return value.replace(/_/g, " ");
}

function previewValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function fileValidationError(file: File | null, maxBytes: number | undefined): string {
  if (!file) return "Choose a CSV or XLSX review export.";
  if (!/\.(csv|xlsx)$/i.test(file.name)) return "This file must be CSV or XLSX.";
  if (maxBytes && file.size > maxBytes) return `This file exceeds the ${(maxBytes / 1_000_000).toFixed(1)} MB limit.`;
  return "";
}

export function ReviewImportPanel({ onImported }: ReviewImportPanelProps) {
  const [config, setConfig] = useState<ImportConfigResponse | null>(null);
  const [lastImportByProfile, setLastImportByProfile] = useState<Partial<Record<ReviewImportProfile, string | null>>>({});
  const [configError, setConfigError] = useState("");
  const [configAttempt, setConfigAttempt] = useState(0);
  const [profile, setProfile] = useState<ReviewImportProfile | "">("");
  const [file, setFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [preview, setPreview] = useState<ImportPreviewResponse | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [previewBusy, setPreviewBusy] = useState(false);
  const [run, setRun] = useState<RunResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<"importing" | "finishing" | null>(null);
  const activeRequest = useRef<AbortController | null>(null);
  const previewRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setConfigError("");
    fetchImportConfig(controller.signal)
      .then((value) => {
        setConfig(value);
        setLastImportByProfile(value.last_import_by_profile);
        setProfile((current) => current || value.profiles[0] || "");
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setConfigError(errorMessage(cause));
      });
    return () => controller.abort();
  }, [configAttempt]);

  useEffect(() => () => {
    activeRequest.current?.abort();
    previewRequest.current?.abort();
    activeRequest.current = null;
    previewRequest.current = null;
  }, []);

  useEffect(() => {
    previewRequest.current?.abort();
    setPreview(null);
    setPreviewError("");
    setPreviewBusy(false);
    if (!file || !profile || !config?.enabled) return;

    const validation = fileValidationError(file, config.max_bytes);
    if (validation) {
      setPreviewError(validation);
      return;
    }

    const controller = new AbortController();
    previewRequest.current = controller;
    setPreviewBusy(true);
    const request = config.agentic_detection_enabled
      ? detectReviewImport(file, profile, controller.signal)
      : previewReviewImport(file, profile, controller.signal);

    request
      .then((value) => {
        if (controller.signal.aborted) return;
        setPreview(value);
        if (value.duplicate_file) {
          setPreviewError("This exact file was already imported. Choose a newer export.");
        } else if (value.valid_rows < 1) {
          setPreviewError(value.issues[0]?.message || "No valid reviews were found in this file.");
        }
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setPreviewError(errorMessage(cause));
      })
      .finally(() => {
        if (previewRequest.current === controller) {
          previewRequest.current = null;
          setPreviewBusy(false);
        }
      });

    return () => controller.abort();
  }, [config?.agentic_detection_enabled, config?.enabled, config?.max_bytes, file, profile]);

  const resetResult = () => {
    setRun(null);
    setError("");
  };

  const handleFile = (nextFile: File | null) => {
    setFile(nextFile);
    resetResult();
  };

  const markLastImport = (importedProfile: ReviewImportProfile, completedAt: string | null | undefined) => {
    setLastImportByProfile((current) => ({
      ...current,
      [importedProfile]: completedAt || new Date().toISOString(),
    }));
  };

  const finishRun = async (result: RunResponse, importedProfile: ReviewImportProfile) => {
    setRun(result);
    if (result.status === "failed") {
      setError(result.error_summary || "The import failed.");
      return;
    }
    if (result.status === "completed" || result.status === "partial") {
      markLastImport(importedProfile, result.completed_at);
      await onImported();
    }
  };

  const pollRun = async (runId: string, controller: AbortController, importedProfile: ReviewImportProfile) => {
    setBusy("finishing");
    const terminal = await waitForRun(runId, {
      signal: controller.signal,
      onUpdate: (update) => setRun(update),
    });
    await finishRun(terminal, importedProfile);
  };

  const handleImport = async () => {
    const selectedProfile = profile || "";
    const validation = fileValidationError(file, config?.max_bytes);
    if (validation) {
      setError(validation);
      return;
    }
    if (!selectedProfile) {
      setError("Choose where this export came from.");
      return;
    }
    if (!preview || previewBusy) {
      setError("Wait for the preview before importing.");
      return;
    }
    if (previewError || preview.duplicate_file || preview.valid_rows < 1) {
      setError(previewError || "Resolve the preview warnings before importing.");
      return;
    }

    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setError("");
    setRun(null);
    setBusy("importing");
    try {
      const queued = preview.mapping
        ? await commitReviewImport(file as File, selectedProfile, controller.signal, preview.mapping)
        : await commitReviewImport(file as File, selectedProfile, controller.signal);
      setRun(queued);
      if (queued.status === "queued" || queued.status === "running") {
        await pollRun(queued.pipeline_run_id, controller, selectedProfile);
      } else {
        await finishRun(queued, selectedProfile);
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

  const buttonLabel = busy === "importing"
    ? "Importing..."
    : busy === "finishing"
      ? "Finishing..."
      : "Import data";

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
  const canImport = Boolean(file && profile && preview && !previewBusy && !previewError && !preview.duplicate_file && preview.valid_rows > 0);
  const previewColumns = preview?.samples.length
    ? PREVIEW_COLUMNS.filter((column) => preview.samples.some((sample) => sample[column] !== undefined))
    : [];
  const mappingEntries = preview ? Object.entries(preview.resolved_mapping) : [];

  return (
    <Stack as="section" aria-labelledby="review-import-title" gap="8" w="full">
      <Flex align={{ base: "flex-start", md: "center" }} justify="space-between" gap="4" wrap="wrap">
        <Flex align="center" gap="3">
          <Flex w="11" h="11" align="center" justify="center" borderRadius="control" bg="orange.100" color="orange.700" flexShrink="0">
            <UploadSimple size={23} weight="bold" />
          </Flex>
          <Box>
            <Heading id="review-import-title" size="xl" letterSpacing="0">Import reviews</Heading>
            <Text color="muted" fontSize="sm">Preview a marketplace export, then import the reviewed rows.</Text>
          </Box>
        </Flex>
      </Flex>

      <Stack gap="3">
        <Text fontSize="sm" fontWeight="700">Marketplace</Text>
        <Flex role="radiogroup" aria-label="Marketplace" gap="2.5" wrap={{ base: "wrap", xl: "nowrap" }} align="stretch">
          {config.profiles.map((value) => {
            const selected = profile === value;
            return (
              <Flex
                key={value}
                as="label"
                align="center"
                justify="center"
                direction="column"
                gap="2"
                flex={{ base: "1 1 190px", xl: "1 1 0" }}
                minW={{ base: "180px", xl: "0" }}
                minH="104px"
                px="3.5"
                py="3"
                borderWidth="1px"
                borderColor={selected ? "accent" : "border"}
                borderRadius="control"
                bg={selected ? "orange.50" : "surface"}
                color={selected ? "accent" : "ink"}
                _dark={{ bg: selected ? "#24150d" : "surface" }}
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
                <Flex
                  align="center"
                  justify="center"
                  h="10"
                  minW={value === "guardian_ecommerce" ? "112px" : "0"}
                  px={value === "guardian_ecommerce" ? "3" : "0"}
                  borderRadius="control"
                  bg={value === "guardian_ecommerce" ? "#f58220" : "transparent"}
                >
                  <Box asChild h={value === "guardian_ecommerce" ? "5" : "8"} maxW="132px" objectFit="contain">
                    <img src={PROFILE_LOGOS[value]} alt="" aria-hidden="true" />
                  </Box>
                </Flex>
                <Box minW="0" textAlign="center">
                  <Text color={selected ? "accent" : "muted"} fontSize="xs" lineHeight="1.35">Last import: {importTime(lastImportByProfile[value] ?? null)}</Text>
                </Box>
              </Flex>
            );
          })}
        </Flex>
      </Stack>

      <Stack gap="4" w="full">
        <Flex
          as="label"
          position="relative"
          w="full"
          minH={{ base: "230px", md: "270px" }}
          px={{ base: "5", md: "6" }}
          py="7"
          direction="column"
          align="center"
          justify="center"
          gap="4"
          textAlign="center"
          borderWidth="2px"
          borderStyle="dashed"
          borderColor={dragActive || file ? "accent" : "border"}
          borderRadius="control"
          bg={dragActive || file ? "orange.50" : "surface"}
          _dark={{ bg: dragActive || file ? "#24150d" : "surface" }}
          cursor={locked ? "not-allowed" : "pointer"}
          onDragOver={(event) => { event.preventDefault(); if (!locked) setDragActive(true); }}
          onDragLeave={() => setDragActive(false)}
          onDrop={handleDrop}
        >
          <Flex w="14" h="14" align="center" justify="center" borderRadius="control" bg="canvas" color="accent" borderWidth="1px" borderColor="border">
            <FileCsv size={31} weight={file ? "fill" : "regular"} />
          </Flex>
          <Stack gap="1" maxW="480px" align="center">
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

        <Button w="full" h="52px" colorPalette="orange" disabled={locked || !canImport} onClick={handleImport}>
          {busy && <Spinner size="xs" />}
          {buttonLabel}
        </Button>

        {previewBusy && <Flex align="center" justify="center" gap="2" color="muted" fontSize="sm" role="status"><Spinner size="xs" />Previewing file...</Flex>}
        {config.agentic_detection_enabled === false && <Text color="muted" fontSize="sm" textAlign="center">Automatic detection is unavailable.</Text>}
      </Stack>

      {preview && (
        <Stack gap="4" minW="0">
          <Flex gap="6" wrap="wrap" justify="center">
            <Box textAlign="center"><Text fontSize="xl" fontWeight="750">{preview.total_rows.toLocaleString()}</Text><Text color="muted" fontSize="sm">rows found</Text></Box>
            <Box textAlign="center"><Text fontSize="xl" fontWeight="750">{preview.valid_rows.toLocaleString()}</Text><Text color="muted" fontSize="sm">ready</Text></Box>
            <Box textAlign="center"><Text fontSize="xl" fontWeight="750">{preview.invalid_rows.toLocaleString()}</Text><Text color="muted" fontSize="sm">flagged</Text></Box>
          </Flex>

          {mappingEntries.length > 0 && (
            <Flex gap="2" wrap="wrap" justify="center">
              {mappingEntries.map(([target, source]) => (
                <Box key={target} px="2.5" py="1.5" borderWidth="1px" borderColor="border" borderRadius="control" bg="surface" fontSize="xs">
                  <Text as="span" color="muted">{shortColumnLabel(target)}: </Text>{source}
                </Box>
              ))}
            </Flex>
          )}

          {previewColumns.length > 0 ? (
            <Box overflowX="auto" borderWidth="1px" borderColor="border" borderRadius="control">
              <Box as="table" w="full" minW="720px" fontSize="sm" borderCollapse="collapse">
                <Box as="thead" bg="subtle">
                  <Box as="tr">
                    {previewColumns.map((column) => <Box as="th" key={column} px="3" py="2.5" textAlign="left" fontWeight="700">{shortColumnLabel(column)}</Box>)}
                  </Box>
                </Box>
                <Box as="tbody">
                  {preview.samples.map((sample, index) => (
                    <Box as="tr" key={`${preview.file_sha256}-${index}`} borderTopWidth="1px" borderColor="border">
                      {previewColumns.map((column) => (
                        <Box as="td" key={column} px="3" py="2.5" verticalAlign="top" maxW={column === "text" ? "360px" : "220px"}>
                          <Text lineClamp={column === "text" ? 3 : 2}>{previewValue(sample[column])}</Text>
                        </Box>
                      ))}
                    </Box>
                  ))}
                </Box>
              </Box>
            </Box>
          ) : (
            <Text color="muted" fontSize="sm" textAlign="center">No sample rows are available for this file.</Text>
          )}

          {preview.issues.length > 0 && (
            <Stack gap="2">
              <Text fontSize="sm" fontWeight="700">Rows needing attention</Text>
              {preview.issues.slice(0, 5).map((issue, index) => (
                <Flex key={`${issue.row_number}-${issue.code}-${index}`} gap="2" fontSize="sm" color="muted">
                  <Text flexShrink="0" fontWeight="700" color="ink">Row {issue.row_number || index + 1}</Text>
                  <Text>{issue.message}</Text>
                </Flex>
              ))}
            </Stack>
          )}
        </Stack>
      )}

      {busy && <Flex align="center" gap="2" color="muted" fontSize="sm" role="status"><Spinner size="xs" />{buttonLabel}</Flex>}
      {run?.status === "completed" && <Flex p="4" gap="3" borderLeftWidth="4px" borderColor="success" bg="surface" role="status"><CheckCircle size={19} weight="fill" /><Box><Text fontWeight="700">Import complete</Text><Text color="muted" fontSize="sm">{run.records_inserted.toLocaleString()} new - {run.records_skipped.toLocaleString()} skipped - {run.records_failed.toLocaleString()} failed</Text></Box></Flex>}
      {run?.status === "partial" && <Flex p="4" gap="3" borderLeftWidth="4px" borderColor="orange.500" bg="surface" role="status"><WarningCircle size={19} /><Box><Text fontWeight="700">Some reviews could not be imported</Text><Text color="muted" fontSize="sm">{run.records_inserted.toLocaleString()} imported - {run.records_failed.toLocaleString()} failed</Text></Box></Flex>}
      {previewError && <Flex p="4" gap="3" borderLeftWidth="4px" borderColor="danger" bg="surface" role="alert"><WarningCircle size={18} /><Text>{previewError}</Text></Flex>}
      {error && <Flex p="4" gap="3" borderLeftWidth="4px" borderColor="danger" bg="surface" role="alert"><WarningCircle size={18} /><Text>{error}</Text></Flex>}
    </Stack>
  );
}
