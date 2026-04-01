import { useState, useEffect, useRef, useCallback } from "react";
import { getTask } from "../api";

/**
 * Polls a task until it reaches a terminal state.
 * Tries SSE first, falls back to polling.
 *
 * @param {string|null} taskId - Task ID to track
 * @param {object} options
 * @param {number} options.interval - Polling interval in ms (default 2000)
 * @param {boolean} options.enabled - Whether to poll (default true)
 * @returns {{ task, events, isComplete, isError }}
 */
export default function useTaskPoller(taskId, { interval = 2000, enabled = true } = {}) {
  const [task, setTask] = useState(null);
  const [events, setEvents] = useState([]);
  const [isComplete, setIsComplete] = useState(false);
  const [isError, setIsError] = useState(false);
  const cleanupRef = useRef(null);

  const checkTerminal = useCallback((status) => {
    if (["completed", "failed", "blocked"].includes(status)) {
      setIsComplete(true);
      if (status === "failed") setIsError(true);
      return true;
    }
    return false;
  }, []);

  useEffect(() => {
    if (!taskId || !enabled) return;

    // Reset state for new task
    setTask(null);
    setEvents([]);
    setIsComplete(false);
    setIsError(false);

    let stopped = false;

    // Try SSE first
    const sseUrl = `/api/agents/tasks/${taskId}/stream`;
    let es = null;

    try {
      es = new EventSource(sseUrl);
      let sseWorking = false;

      es.addEventListener("progress", (e) => {
        sseWorking = true;
        try {
          const data = JSON.parse(e.data);
          setEvents((prev) => [...prev, { event_type: "progress", ...data }]);
        } catch { /* ignore parse errors */ }
      });

      es.addEventListener("started", (e) => {
        sseWorking = true;
        setEvents((prev) => [...prev, { event_type: "started" }]);
      });

      es.addEventListener("task_update", (e) => {
        sseWorking = true;
        try {
          const data = JSON.parse(e.data);
          setTask((prev) => prev ? { ...prev, status: data.status } : { status: data.status });
        } catch { /* ignore */ }
      });

      es.addEventListener("done", (e) => {
        try {
          const data = JSON.parse(e.data);
          checkTerminal(data.final_status);
        } catch { /* ignore */ }
        es.close();
      });

      es.addEventListener("completed", () => {
        // Fetch the full task to get output_data
        getTask(taskId).then((t) => {
          setTask(t);
          setIsComplete(true);
        }).catch(() => {});
      });

      es.addEventListener("blocked", () => {
        getTask(taskId).then((t) => {
          setTask(t);
          setIsComplete(true);
        }).catch(() => {});
      });

      es.addEventListener("failed", () => {
        getTask(taskId).then((t) => {
          setTask(t);
          setIsComplete(true);
          setIsError(true);
        }).catch(() => {});
      });

      es.onerror = () => {
        es.close();
        if (!sseWorking && !stopped) {
          // SSE not available, fall back to polling
          startPolling();
        }
      };

      cleanupRef.current = () => {
        stopped = true;
        es.close();
      };
    } catch {
      // EventSource not available, fall back to polling
      startPolling();
    }

    function startPolling() {
      const poll = async () => {
        if (stopped) return;
        try {
          const t = await getTask(taskId);
          if (stopped) return;
          setTask(t);
          if (checkTerminal(t.status)) return;
          setTimeout(poll, interval);
        } catch {
          if (!stopped) setTimeout(poll, interval * 2);
        }
      };
      poll();
      cleanupRef.current = () => { stopped = true; };
    }

    return () => {
      stopped = true;
      if (cleanupRef.current) cleanupRef.current();
    };
  }, [taskId, enabled, interval, checkTerminal]);

  return { task, events, isComplete, isError };
}
