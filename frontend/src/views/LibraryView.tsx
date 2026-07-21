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
      title: "Practice any problem.",
      description: "Search by title, number, or slug and start a paper session on anything — scheduled work stays scheduled.",
    },
    queue: {
      title: "The queue, without the pile-up.",
      description: "Maintain learning obligations in bulk. State changes never rewrite evidence.",
    },
    reviews: {
      title: "Reviews ordered by evidence.",
      description: "Overdue and upcoming reconstruction work, separated from the backlog.",
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
        eyebrow={sub === "reviews" ? "Adaptive retrieval inbox" : "Problem library"}
        title={copy.title}
        description={copy.description}
        allowBulk={sub === "queue"}
        showTrackFilter
      />
    </div>
  );
}
