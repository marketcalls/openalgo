export interface PendingResponse {
  readonly url: string;
  readonly init: RequestInit;
  reply(payload: unknown, status?: number): void;
  fail(error: Error): void;
}

/** Deferred responses deliberately ignore abort to expose stale-result races. */
export class ControlledTransport {
  public readonly requests: PendingResponse[] = [];

  public readonly fetch: typeof fetch = (input, init = {}) => new Promise<Response>((resolve, reject) => {
    this.requests.push({
      url: String(input), init,
      reply: (payload, status = 200) => resolve({
        ok: status >= 200 && status < 300, status, json: async () => payload,
      } as Response),
      fail: reject,
    });
  });

  public async request(index: number): Promise<PendingResponse> {
    for (let turn = 0; turn < 100; turn++) {
      const request = this.requests[index];
      if (request) return request;
      await Promise.resolve();
    }
    throw new Error(`Adapter did not request synthetic response ${index}`);
  }
}
