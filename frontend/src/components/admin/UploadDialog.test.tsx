import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UploadDialog } from "./UploadDialog";
import { mockMatchMedia } from "../../test/matchMedia";

/** A file the browser would hand over for a chosen input. */
function file(name: string, bytes = 1024): File {
  return new File([new Uint8Array(bytes)], name, { type: "application/pdf" });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("UploadDialog", () => {
  it("refuses a file over the limit and says what to do instead", async () => {
    mockMatchMedia(1280);
    render(
      <UploadDialog token="t" onClose={() => undefined} onUploaded={() => undefined} />,
    );

    const input = screen.getByLabelText("Choose a file");
    await userEvent.upload(input, file("big.pdf", 21 * 1024 * 1024));
    await userEvent.click(screen.getByRole("button", { name: "Upload" }));

    // Section 8: "validation messages appear under the field", and the message
    // states the next action rather than apologising (section 9).
    expect(await screen.findByText(/limit is 20 MB/)).toBeInTheDocument();
  });

  it("refuses a file type the server would reject", async () => {
    // Dropped rather than picked. The input's `accept` attribute filters the
    // picker, so a wrong type cannot reach the dialog that way -- but a drop
    // bypasses `accept` entirely, which is why the check exists.
    mockMatchMedia(1280);
    render(
      <UploadDialog token="t" onClose={() => undefined} onUploaded={() => undefined} />,
    );

    const dropZone = screen.getByText("Drag a PDF, DOCX, or TXT file here, or").parentElement;
    fireEvent.drop(dropZone as HTMLElement, {
      dataTransfer: { files: [file("notes.exe")] },
    });
    await userEvent.click(screen.getByRole("button", { name: "Upload" }));

    expect(await screen.findByText(/not supported/)).toBeInTheDocument();
  });

  it("requires a category even when a file and title are given", async () => {
    mockMatchMedia(1280);
    render(
      <UploadDialog token="t" onClose={() => undefined} onUploaded={() => undefined} />,
    );

    await userEvent.upload(screen.getByLabelText("Choose a file"), file("schedule.pdf"));
    // The title is filled from the filename, so only the category is missing.
    expect(screen.getByLabelText("Title")).toHaveValue("schedule");

    await userEvent.click(screen.getByRole("button", { name: "Upload" }));
    expect(await screen.findByText("Choose a category.")).toBeInTheDocument();
  });

  it("ties a validation message to its field for a screen reader", async () => {
    mockMatchMedia(1280);
    render(
      <UploadDialog token="t" onClose={() => undefined} onUploaded={() => undefined} />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Upload" }));
    const message = await screen.findByText("Choose a file to upload.");
    const input = screen.getByLabelText("Choose a file");

    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute("aria-describedby", message.id);
  });

  it("names the current step while it works, as a determinate bar", async () => {
    mockMatchMedia(1280);
    vi.stubGlobal("XMLHttpRequest", StubXhr);
    render(
      <UploadDialog token="t" onClose={() => undefined} onUploaded={() => undefined} />,
    );

    await userEvent.upload(screen.getByLabelText("Choose a file"), file("schedule.pdf"));
    await userEvent.selectOptions(screen.getByLabelText("Category"), "examinations");
    await userEvent.click(screen.getByRole("button", { name: "Upload" }));

    // Section 8's first named step, on a bar that reports a value rather than
    // spinning.
    const bar = await screen.findByRole("progressbar", { name: "Upload progress" });
    expect(bar).toHaveAttribute("aria-valuenow", "0");
    expect(screen.getByText("Uploading")).toBeInTheDocument();
  });

  it("closes on Escape from the form", async () => {
    mockMatchMedia(1280);
    const onClose = vi.fn();
    render(<UploadDialog token="t" onClose={onClose} onUploaded={() => undefined} />);

    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("moves focus to the file field when it opens", () => {
    mockMatchMedia(1280);
    render(
      <UploadDialog token="t" onClose={() => undefined} onUploaded={() => undefined} />,
    );
    expect(screen.getByLabelText("Choose a file")).toHaveFocus();
  });
});

/**
 * Enough of `XMLHttpRequest` for the progress path: `open` and `send` do
 * nothing, and nothing ever completes, so the dialog stays in its first step.
 * jsdom's own implementation would attempt a real request.
 */
class StubXhr {
  upload = { addEventListener: () => undefined };
  status = 0;
  responseText = "";
  open() {}
  setRequestHeader() {}
  addEventListener() {}
  send() {}
}
