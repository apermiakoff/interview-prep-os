import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { deriveFacts, FinishSheet, previewLine } from "../src/components/FinishSheet";

describe("deriveFacts", () => {
  test("independent outcome with no hints records a green independent attempt", () => {
    expect(deriveFacts("independent", false, true, "", 4)).toEqual({
      result: "green",
      accepted: true,
      independent: true,
      failure_tag: "none",
      explanation_score: 4,
    });
  });

  test("hints strip independence even if the outcome claims it", () => {
    expect(deriveFacts("independent", true, true, "")).toMatchObject({
      result: "green",
      independent: false,
    });
  });

  test("assisted and solution outcomes carry the blocker and never independence", () => {
    expect(deriveFacts("assisted", true, true, "implementation")).toEqual({
      result: "yellow",
      accepted: true,
      independent: false,
      failure_tag: "implementation",
      explanation_score: undefined,
    });
    expect(deriveFacts("solution", false, false, "derivation")).toMatchObject({
      result: "red",
      independent: false,
      failure_tag: "derivation",
    });
  });

  test("skipped clears accepted and explanation", () => {
    expect(deriveFacts("skipped", false, true, "bugs", 3)).toEqual({
      result: "skipped",
      accepted: false,
      independent: false,
      failure_tag: "unspecified",
      explanation_score: undefined,
    });
  });
});

test("previewLine states the exact record", () => {
  const facts = deriveFacts("assisted", true, true, "implementation", 3);
  expect(previewLine(facts, "H2", 23)).toBe(
    "Records: yellow · assisted · H2 · accepted · blocker: implementation · explains 3/5 · 23 min",
  );
});

test("FinishSheet disables Independent after hints and requires a blocker for red", () => {
  const onSubmit = vi.fn();
  render(
    <FinishSheet
      origin="ad_hoc"
      hintsUsed
      highestHint="H2"
      elapsedMinutes={12}
      busy={false}
      error=""
      onSubmit={onSubmit}
      onClose={() => {}}
    />,
  );
  const independent = screen.getByRole("radio", { name: /Independent/ });
  expect(independent).toBeDisabled();
  expect(screen.getByText(/Hints used through H2/)).toBeInTheDocument();

  const record = screen.getByRole("button", { name: "Record attempt" });
  expect(record).toBeDisabled();

  fireEvent.click(screen.getByRole("radio", { name: /Needed solution/ }));
  expect(record).toBeDisabled(); // blocker still missing
  fireEvent.change(screen.getByLabelText(/Primary blocker/), { target: { value: "derivation" } });
  expect(record).toBeEnabled();

  expect(screen.getByTestId("finish-preview").textContent).toContain("red");
  expect(screen.getByTestId("finish-preview").textContent).toContain("blocker: derivation");

  fireEvent.click(record);
  expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
    result: "red",
    independent: false,
    failure_tag: "derivation",
  }));
});
