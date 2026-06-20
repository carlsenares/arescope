// @ts-check
import { defineConfig } from 'astro/config';

// Static output — zero client JS by default. No third-party CDNs (fonts are
// self-hosted via @fontsource). Deploys as plain files behind the shared nginx.
export default defineConfig({
  site: 'https://arescope.com',
  compressHTML: true,
  prefetch: false,
});
