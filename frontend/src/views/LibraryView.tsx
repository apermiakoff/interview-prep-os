import type { Bootstrap } from "../types";
import { ProblemCollectionView } from "./ProblemCollectionView";

const SUBVIEWS = [
  ["all", "Problems", "library"],
  ["queue", "Queue", "library/queue"],
  ["reviews", "Reviews", "library/reviews"],
] as const;

export function LibraryView({ data, navigate, sub }: { data: Bootstrap; navigate: (route: string) => void; sub: "all" | "queue" | "reviews" }) {
  const copy = {
    all: {
      title: "Problems",
      description: "Search the catalog and start a focused practice session.",
    },
    queue: {
      title: "Queue",
      description: "Manage practice obligations in bulk without changing evidence.",
    },
    reviews: {
      title: "Reviews",
      description: "Overdue and upcoming reconstruction work ordered by evidence.",
    },
  }[sub];

  return (
    <div className="library-shell">
      <nav className="library-tabs" aria-label="Library sections">
        {SUBVIEWS.map(([key, label, route]) => (
          <button key={key} className={sub === key ? "active" : ""} onClick={() => navigate(route)} aria-current={sub === key ? "page" : undefined}>{label}</button>
        ))}
      </nav>
      <ProblemCollectionView
        key={sub}
        data={data}
        navigate={navigate}
        scope={sub === "all" ? "all" : sub}
        eyebrow="Library"
        title={copy.title}
        description={copy.description}
        allowBulk={sub === "queue"}
        showTrackFilter
      />
    </div>
  );
}
