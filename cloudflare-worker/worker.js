const BASE_URL = "https://lichess-puzzle-slack-bot.vercel.app";

const ROUTES = {
  "50 10 * * *": "/admin/puzzle:revealSolution",
  "0 11 * * *": "/admin/leaderboard:send",
  "30 11 * * *": "/admin/dailyPuzzle:send",
};

export default {
  async scheduled(event, env, ctx) {
    const path = ROUTES[event.cron];
    if (!path) return;

    const res = await fetch(`${BASE_URL}${path}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${env.CRON_SECRET}` },
    });

    if (!res.ok) {
      throw new Error(`${path} failed: ${res.status} ${await res.text()}`);
    }
  },
};
