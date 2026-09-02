import { useCallback, useEffect, useRef } from "react";

const EDGE_PADDING = 4;
const ANCHOR_PADDING = 8;
const SCROLL_EPSILON = 4;
const SCROLL_SETTLE_MS = 200;

const DEBUG_TRANSCRIPT_SCROLL = import.meta.env.DEV;

function getVisibleSegmentIndices(
  container: HTMLElement,
  segmentRefs: (HTMLElement | null)[],
): number[] {
  const containerRect = container.getBoundingClientRect();
  const visible: number[] = [];
  segmentRefs.forEach((el, index) => {
    if (!el) return;
    const rect = el.getBoundingClientRect();
    if (
      rect.bottom > containerRect.top + EDGE_PADDING &&
      rect.top < containerRect.bottom - EDGE_PADDING
    ) {
      visible.push(index);
    }
  });
  return visible;
}

function isSegmentOutsideViewport(el: HTMLElement, container: HTMLElement): boolean {
  const containerRect = container.getBoundingClientRect();
  const rect = el.getBoundingClientRect();
  return (
    rect.bottom <= containerRect.top + EDGE_PADDING ||
    rect.top >= containerRect.bottom - EDGE_PADDING
  );
}

function scrollElementToTop(
  container: HTMLElement,
  segmentEl: HTMLElement,
  behavior: ScrollBehavior,
): void {
  const containerRect = container.getBoundingClientRect();
  const segmentRect = segmentEl.getBoundingClientRect();
  const delta = segmentRect.top - containerRect.top - ANCHOR_PADDING;
  if (Math.abs(delta) < SCROLL_EPSILON) return;
  container.scrollTo({ top: container.scrollTop + delta, behavior });
}

type ScrollDebugState = {
  activeIndex: number;
  visibleRange: string;
  triggerIndex: number;
  lastScrolledTriggerIndex: number | null;
  isAutoScrolling: boolean;
};

function logScrollDebug(state: ScrollDebugState, message?: string) {
  if (!DEBUG_TRANSCRIPT_SCROLL) return;
  if (message) {
    console.debug(`[transcript-scroll] ${message}`, state);
    return;
  }
  console.debug("[transcript-scroll]", state);
}

export function useTranscriptBatchScroll(activeSegmentIndex: number, segmentCount: number) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const segmentRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const lastScrolledTriggerIndexRef = useRef<number | null>(null);
  const isAutoScrollingRef = useRef(false);
  const scrollEndTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const resetScrollState = useCallback(() => {
    lastScrolledTriggerIndexRef.current = null;
  }, []);

  const scrollSegmentToTop = useCallback((index: number, behavior: ScrollBehavior = "smooth") => {
    const container = containerRef.current;
    const segmentEl = segmentRefs.current[index];
    if (!container || !segmentEl) return;
    scrollElementToTop(container, segmentEl, behavior);
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const onScroll = () => {
      isAutoScrollingRef.current = true;
      if (scrollEndTimerRef.current) {
        clearTimeout(scrollEndTimerRef.current);
      }
      scrollEndTimerRef.current = setTimeout(() => {
        isAutoScrollingRef.current = false;
      }, SCROLL_SETTLE_MS);
    };

    container.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      container.removeEventListener("scroll", onScroll);
      if (scrollEndTimerRef.current) {
        clearTimeout(scrollEndTimerRef.current);
      }
    };
  }, [segmentCount]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const observer = new ResizeObserver(() => {
      lastScrolledTriggerIndexRef.current = null;
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [segmentCount]);

  useEffect(() => {
    resetScrollState();
  }, [segmentCount, resetScrollState]);

  useEffect(() => {
    if (activeSegmentIndex < 0) return;

    const container = containerRef.current;
    const activeEl = segmentRefs.current[activeSegmentIndex];
    if (!container || !activeEl) return;

    const visible = getVisibleSegmentIndices(container, segmentRefs.current);
    const triggerIndex = visible.length >= 2 ? visible[visible.length - 2] : -1;
    const debugState: ScrollDebugState = {
      activeIndex: activeSegmentIndex,
      visibleRange:
        visible.length > 0 ? `${visible[0]}-${visible[visible.length - 1]}` : "none",
      triggerIndex,
      lastScrolledTriggerIndex: lastScrolledTriggerIndexRef.current,
      isAutoScrolling: isAutoScrollingRef.current,
    };

    if (isSegmentOutsideViewport(activeEl, container)) {
      logScrollDebug(debugState, "RECOVERY SCROLL");
      lastScrolledTriggerIndexRef.current = null;
      scrollElementToTop(container, activeEl, "auto");
      return;
    }

    if (visible.length < 2 || triggerIndex < 0) {
      logScrollDebug(debugState);
      return;
    }

    if (isAutoScrollingRef.current) {
      logScrollDebug(debugState, "skip (scroll in progress)");
      return;
    }

    if (
      activeSegmentIndex === triggerIndex &&
      lastScrolledTriggerIndexRef.current !== triggerIndex
    ) {
      logScrollDebug(debugState, "AUTO SCROLL");
      scrollElementToTop(container, activeEl, "smooth");
      lastScrolledTriggerIndexRef.current = triggerIndex;
      return;
    }

    logScrollDebug(debugState);
  }, [activeSegmentIndex]);

  return {
    containerRef,
    segmentRefs,
    resetScrollState,
    scrollSegmentToTop,
  };
}
