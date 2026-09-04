const config = require("@nicxe/semantic-release-config")({
  componentDir: "custom_components/smhi_weather_context",
  manifestPath: "custom_components/smhi_weather_context/manifest.json",
  projectName: "SMHI Weather Context",
  repoSlug: "Nicxe/smhi_weather_context",
  notifyIssues: false
});

const githubPlugin = config.plugins.find(
  (plugin) => Array.isArray(plugin) && plugin[0] === "@semantic-release/github"
);

if (githubPlugin?.[1]) {
  githubPlugin[1].successCommentCondition = false;
  githubPlugin[1].assets = [
    { path: "smhi_weather_context.zip", label: "SMHI Weather Context" },
    { path: "smhi_weather_context.zip.sha256", label: "SHA-256 checksum" },
    { path: "smhi_weather_context.zip.spdx.json", label: "SPDX SBOM" }
  ];
}

const execPlugin = config.plugins.find(
  (plugin) => Array.isArray(plugin) && plugin[0] === "@semantic-release/exec"
);

if (execPlugin?.[1]) {
  execPlugin[1].prepareCmd = [
    "python3 scripts/build_release.py",
    "--component custom_components/smhi_weather_context",
    "--output smhi_weather_context.zip",
    "--version ${nextRelease.version}"
  ].join(" ");
}

module.exports = config;
