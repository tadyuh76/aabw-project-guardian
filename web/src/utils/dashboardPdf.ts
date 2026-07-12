import html2canvas from "html2canvas";
import { jsPDF } from "jspdf";

interface DashboardCaptureOptions {
  filename?: string;
}

export async function captureDashboardPdf(element: HTMLElement, options: DashboardCaptureOptions = {}): Promise<void> {
  const canvas = await html2canvas(element, {
    backgroundColor: "#f8fafc",
    scale: Math.min(2, window.devicePixelRatio || 1),
    useCORS: true,
    onclone: (documentClone) => {
      documentClone.querySelectorAll("[data-pdf-hidden='true']").forEach((node) => {
        if (node instanceof HTMLElement) node.style.display = "none";
      });
      documentClone.querySelectorAll("[data-pdf-capture='dashboard']").forEach((node) => {
        if (node instanceof HTMLElement) {
          node.style.width = `${element.scrollWidth}px`;
          node.style.maxWidth = "none";
        }
      });
    },
  });

  const pdf = new jsPDF({ orientation: "portrait", unit: "pt", format: "a4" });
  const pageWidth = pdf.internal.pageSize.getWidth();
  const pageHeight = pdf.internal.pageSize.getHeight();
  const margin = 24;
  const contentWidth = pageWidth - margin * 2;
  const contentHeight = pageHeight - margin * 2;
  const imageWidth = contentWidth;
  const imageHeight = (canvas.height * imageWidth) / canvas.width;
  const imageData = canvas.toDataURL("image/png");

  let renderedHeight = 0;
  let pageIndex = 0;
  while (renderedHeight < imageHeight) {
    if (pageIndex > 0) pdf.addPage();
    pdf.addImage(imageData, "PNG", margin, margin - renderedHeight, imageWidth, imageHeight);
    renderedHeight += contentHeight;
    pageIndex += 1;
  }

  pdf.save(options.filename ?? "guardian-dashboard.pdf");
}
