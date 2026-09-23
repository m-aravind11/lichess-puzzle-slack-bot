/**
 * Welcome to Cloudflare Workers! This is your first worker.
 *
 * - Run "npm run dev" in your terminal to start a development server
 * - Open a browser tab at http://localhost:8787/ to see your worker in action
 * - Run "npm run deploy" to publish your worker
 *
 * Learn more at https://developers.cloudflare.com/workers/
 */

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
