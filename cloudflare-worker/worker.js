const BASE_URL = "https://lichess-puzzle-slack-bot.vercel.app";

// Prepare queues the next puzzle after each send, and runs again before the next
// send in case that failed.
const ROUTES = {
  "50 10 * * 2-6": ["/admin/puzzle:revealSolution", "/admin/dailyPuzzle:prepare"],
  "0 11 * * 2-6": ["/admin/leaderboard:send"],
  "30 11 * * 2-6": ["/admin/dailyPuzzle:send", "/admin/dailyPuzzle:prepare"],
};

export default {
  async scheduled(event, env, ctx) {
    const paths = ROUTES[event.cron];
    if (!paths) return;

    const failures = [];
    for (const path of paths) {
      try {
        const res = await fetch(`${BASE_URL}${path}`, {
          method: "POST",
          headers: { Authorization: `Bearer ${env.CRON_SECRET}` },
        });
        if (!res.ok) failures.push(`${path} failed: ${res.status} ${await res.text()}`);
      } catch (err) {
        failures.push(`${path} failed: ${err}`);
      }
    }

    if (failures.length) {
      throw new Error(failures.join("\n"));
    }
  },
};
