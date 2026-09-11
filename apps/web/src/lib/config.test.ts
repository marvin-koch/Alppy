/**
 * The web app's configuration gate (D27).
 *
 * `validateWebConfig` is a pure function on a `WebConfig` so the interesting
 * cases can be stated directly, without process-wide environment surgery: the
 * combinations below are the ones that produce a *silently* wrong deployment
 * rather than a loud one.
 */
import { describe, expect, it } from 'vitest';

import {
  type WebConfig,
  assertWebConfig,
  readWebConfig,
  validateWebConfig,
} from './config';

function config(overrides: Partial<WebConfig> = {}): WebConfig {
  return {
    env: 'production',
    isDeployment: true,
    dev: false,
    apiBaseUrl: 'https://alppy.example/api/v1',
    apiOrigin: 'https://alppy.example',
    mediaOrigins: ['https://objects.example'],
    s3PublicOrigin: 'https://objects.example',
    mockEnabled: false,
    demoMode: false,
    ...overrides,
  };
}

describe('validateWebConfig', () => {
  it('passes a coherent production configuration', () => {
    expect(validateWebConfig(config())).toEqual([]);
  });

  /** The finding this module exists for: the review screen renders its rows,
   *  its verdict buttons, and empty frames where the crops should be. */
  it('refuses media origins that do not cover the object store', () => {
    const problems = validateWebConfig(config({ mediaOrigins: [] }));
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain('ALPPY_MEDIA_ORIGINS');
    expect(problems[0]).toContain('https://objects.example');
  });

  it('says nothing about media origins when the web app was never told the endpoint', () => {
    expect(validateWebConfig(config({ s3PublicOrigin: null, mediaOrigins: [] }))).toEqual([]);
  });

  it('refuses an API base that is neither absolute nor same-origin', () => {
    const problems = validateWebConfig(
      config({ apiBaseUrl: 'api/v1', apiOrigin: null, s3PublicOrigin: null, mediaOrigins: [] }),
    );
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain('NEXT_PUBLIC_API_BASE_URL');
  });

  it('accepts the reverse-proxied same-origin base', () => {
    expect(
      validateWebConfig(config({ apiBaseUrl: '/api/v1', apiOrigin: null })),
    ).toEqual([]);
  });

  it('refuses fixture mode and demo mode on a real deployment', () => {
    const problems = validateWebConfig(config({ mockEnabled: true, demoMode: true }));
    expect(problems).toHaveLength(2);
    expect(problems.join(' ')).toContain('NEXT_PUBLIC_ALPPY_MOCK');
    expect(problems.join(' ')).toContain('NEXT_PUBLIC_ALPPY_DEMO_MODE');
  });

  /** Local and CI are what the development defaults are *for*. */
  it('leaves local alone', () => {
    const problems = validateWebConfig(
      config({
        env: 'local',
        isDeployment: false,
        dev: true,
        mockEnabled: true,
        demoMode: true,
        apiBaseUrl: 'http://localhost:8000/api/v1',
        apiOrigin: 'http://localhost:8000',
        mediaOrigins: ['http://localhost:9000'],
        s3PublicOrigin: 'http://localhost:9000',
      }),
    );
    expect(problems).toEqual([]);
  });

  it('refuses plain HTTP for the API and for the object store on a deployment', () => {
    const problems = validateWebConfig(
      config({
        apiBaseUrl: 'http://alppy.example/api/v1',
        apiOrigin: 'http://alppy.example',
        mediaOrigins: ['http://objects.example'],
        s3PublicOrigin: 'http://objects.example',
      }),
    );
    expect(problems).toHaveLength(2);
  });

  /** Collected, not first-wins: a fresh deployment usually has more than one. */
  it('reports every problem at once', () => {
    const problems = validateWebConfig(
      config({ mediaOrigins: [], mockEnabled: true, demoMode: true }),
    );
    expect(problems).toHaveLength(3);
  });
});

describe('assertWebConfig', () => {
  it('throws with every problem named', () => {
    expect(() => assertWebConfig(config({ mediaOrigins: [], demoMode: true }))).toThrow(
      /ALPPY_MEDIA_ORIGINS[\s\S]*NEXT_PUBLIC_ALPPY_DEMO_MODE/,
    );
  });

  it('returns the configuration it was given when it is sound', () => {
    const sound = config();
    expect(assertWebConfig(sound)).toBe(sound);
  });
});

describe('readWebConfig', () => {
  /** The test environment is a development one, which is the whole point of
   *  the `local` default: nothing here should be treated as a deployment. */
  it('defaults ALPPY_ENV to local, so no deployment rule fires', () => {
    const read = readWebConfig();
    expect(read.env).toBe('local');
    expect(read.isDeployment).toBe(false);
  });
});
