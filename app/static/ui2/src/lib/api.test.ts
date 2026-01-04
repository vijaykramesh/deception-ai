import { describe, expect, it, vi } from 'vitest';
import { api } from './api';

describe('api()', () => {
  it('throws a useful error message on non-2xx responses', async () => {
    const fetchMock = vi.fn(async () =>
      new Response('nope', {
        status: 500,
        statusText: 'Server error'
      })
    );

    vi.stubGlobal('fetch', fetchMock);

    await expect(api('/healthcheck')).rejects.toThrow('nope');

    vi.unstubAllGlobals();
  });
});

