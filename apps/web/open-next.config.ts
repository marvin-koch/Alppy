import { defineCloudflareConfig } from '@opennextjs/cloudflare';

/**
 * No incremental cache is configured on purpose.
 *
 * Every screen in this app fetches through TanStack Query in the browser
 * (`src/lib/api/client.ts`) — there is no `fetch` cache, no ISR and no
 * revalidation to persist, so an R2 or KV cache binding would carry nothing.
 * Add one here the day a route starts rendering data on the server.
 */
export default defineCloudflareConfig();
