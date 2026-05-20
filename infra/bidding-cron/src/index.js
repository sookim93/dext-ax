export default {
  async scheduled(event, env, ctx) {
    const res = await fetch(
      "https://api.github.com/repos/sookim93/dext-ax/actions/workflows/daily-digest.yml/dispatches",
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GITHUB_PAT}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": "bidding-cron-worker",
        },
        body: JSON.stringify({ ref: "main" }),
      }
    );

    if (!res.ok) {
      const text = await res.text();
      throw new Error(`GitHub dispatch failed: ${res.status} ${text}`);
    }

    console.log(`Dispatched at ${new Date().toISOString()} — cron: ${event.cron}`);
  },
};
