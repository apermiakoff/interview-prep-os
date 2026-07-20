import { render, screen } from "@testing-library/react";
import { ForgettingCurve } from "../src/components/ForgettingCurve";


test("forgetting curve labels sparse evidence honestly", () => {
  render(<ForgettingCurve memory={{
    problem_id: 1,
    title: "Critical Connections",
    stability_days: 1,
    difficulty: 6,
    retrievability: 1,
    evidence_count: 2,
    last_attempt_on: "2026-07-19",
    next_due: "2026-07-20",
    last_result: "red",
    curve: [{ day: 0, value: 1 }, { day: 1, value: .36 }],
  }} />);
  expect(screen.getByText("2 observations")).toBeInTheDocument();
  expect(screen.getByText(/confidence remains early/i)).toBeInTheDocument();
});
