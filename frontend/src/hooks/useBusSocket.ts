import { useEffect, useRef, useState } from "react";
import { busWebSocketUrl, studioSocketProtocols } from "../api/client";
import type { BusMessage } from "../types";

/**
 * Subscribes to /ws/bus and keeps:
 *  - the most recent message overall (drives the topbar timecode)
 *  - the most recent message per topic (drives the Inspector's "live value" panel)
 *
 * Reconnects automatically with backoff if the backend restarts or the
 * graph hasn't started yet (the socket is opened regardless of graph
 * run-state — messages just won't arrive until something is running).
 */
export function useBusSocket() {
  const [latest, setLatest] = useState<BusMessage | null>(null);
  const [connected, setConnected] = useState(false);
  const byTopicRef = useRef<Map<string, BusMessage>>(new Map());
  const [byTopicVersion, setByTopicVersion] = useState(0);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;
    let pending: BusMessage | null = null;
    const repaint = setInterval(() => {
      if (pending) {
        setLatest(pending);
        setByTopicVersion((v) => v + 1);
        pending = null;
      }
    }, 100);

    function connect() {
      if (cancelled) return;
      socket = new WebSocket(busWebSocketUrl(), studioSocketProtocols());

      socket.onopen = () => setConnected(true);

      socket.onmessage = (event) => {
        try {
          const msg: BusMessage = JSON.parse(event.data);
          pending = msg;
          byTopicRef.current.set(msg.topic, msg);
        } catch {
          // ignore malformed frames rather than crashing the UI
        }
      };

      socket.onclose = () => {
        setConnected(false);
        if (!cancelled) retryTimer = setTimeout(connect, 1500);
      };

      socket.onerror = () => {
        socket?.close();
      };
    }

    connect();
    return () => {
      cancelled = true;
      clearInterval(repaint);
      if (retryTimer) clearTimeout(retryTimer);
      socket?.close();
    };
  }, []);

  function getLatestForTopic(topic: string): BusMessage | undefined {
    return byTopicRef.current.get(topic);
  }

  return { latest, connected, getLatestForTopic, byTopicVersion };
}
