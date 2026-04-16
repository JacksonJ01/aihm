"use client";

import React from "react";
import Link from "next/link";
import { useState, useRef, useEffect, useLayoutEffect, useCallback } from "react";
import { usePathname } from 'next/navigation';
import { createPortal } from "react-dom";
import { createClient } from "@/lib/supabase/client";
import { logoutAction } from "@/app/auth/actions";

const hasSupabaseBrowserEnv = Boolean(
  (process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.NEXT_PUBLIC_aihm_SUPABASE_URL) &&
  (
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ||
    process.env.NEXT_PUBLIC_aihm_SUPABASE_PUBLISHABLE_KEY ||
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ||
    process.env.NEXT_PUBLIC_aihm_SUPABASE_ANON_KEY
  ),
);

export default function NavBar() {
  const [isSignedIn, setIsSignedIn] = useState(false);
  const [isAuthChecking, setIsAuthChecking] = useState(true);
  const [programsOpen, setProgramsOpen] = useState(false);
  const [communityOpen, setCommunityOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const programsCloseTimerRef = useRef<number | null>(null);
  const communityCloseTimerRef = useRef<number | null>(null);
  const profileCloseTimerRef = useRef<number | null>(null);
  const programsRef = useRef<HTMLDivElement | null>(null);
  const communityRef = useRef<HTMLDivElement | null>(null);
  const profileRef = useRef<HTMLDivElement | null>(null);
  const mobileMenuRef = useRef<HTMLDivElement | null>(null);
  const mobileMenuButtonRef = useRef<HTMLButtonElement | null>(null);
  const programsBtnRef = useRef<HTMLButtonElement | null>(null);
  const communityBtnRef = useRef<HTMLButtonElement | null>(null);
  const profileBtnRef = useRef<HTMLButtonElement | null>(null);
  const [isMobile, setIsMobile] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [programsMobileOpen, setProgramsMobileOpen] = useState(false);
  const [communityMobileOpen, setCommunityMobileOpen] = useState(false);
  const [profileMobileOpen, setProfileMobileOpen] = useState(false);
  const [activeMobileTop, setActiveMobileTop] = useState<string | null>(null);
  // Mobile toggles that close other dropdowns when opening
  const toggleProgramsMobile = () => {
    setProgramsMobileOpen(prev => {
      const next = !prev;
      if (next) {
        setCommunityMobileOpen(false);
        setProfileMobileOpen(false);
      }
      return next;
    });
  };
  const toggleCommunityMobile = () => {
    setCommunityMobileOpen(prev => {
      const next = !prev;
      if (next) {
        setProgramsMobileOpen(false);
        setProfileMobileOpen(false);
      }
      return next;
    });
  };
  const toggleProfileMobile = () => {
    setProfileMobileOpen(prev => {
      const next = !prev;
      if (next) {
        setProgramsMobileOpen(false);
        setCommunityMobileOpen(false);
      }
      return next;
    });
  };

  // keep activeMobileTop in sync so only one top item appears active (white) at a time
  const setActiveFor = (key: string | null) => {
    setActiveMobileTop(key);
  };

  // route-aware active styling
  const pathname = usePathname() || '/';
  const notRoot = pathname !== '/';
  const isActivePath = (p: string) => notRoot && pathname.startsWith(p);
  const isProgramsActive = notRoot && ['/programs', '/browsePrograms', '/progress'].some(p => pathname.startsWith(p));
  const startActive = isActivePath('/workouts');
  const communityActive = notRoot && ['/community', '/friends'].some(p => pathname.startsWith(p));
  const notificationsActive = isActivePath('/notifications');
  const profileActive = notRoot && ['/profile', '/help'].some(p => pathname.startsWith(p));

  // treat AIHM as "aware" of the same top-level routes (used for sizing/alignment only)
  // Make AIHM active when any of the main nav items are active so visuals match exactly
  const aiHmActive = notRoot && (startActive || isProgramsActive || communityActive || notificationsActive || profileActive);

  // base style for all top-level nav items so active state doesn't change height
  const navItemBase: React.CSSProperties = {
    whiteSpace: 'nowrap',
    transition: 'color 150ms ease, transform 120ms ease, box-shadow 180ms ease',
    padding: '6px 10px',
    display: 'inline-flex',
    alignItems: 'center',
    background: 'transparent',
    border: 'none',
    color: 'inherit',
    cursor: 'pointer',
    font: 'inherit',
  };
  const signOutButtonBase: React.CSSProperties = {
    background: 'transparent',
    border: 'none',
    color: 'inherit',
    cursor: 'pointer',
    font: 'inherit',
    padding: 0,
    margin: 0,
    textAlign: 'left',
  };
  const clearCloseTimer = (timerRef: React.MutableRefObject<number | null>) => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const openProgramsMenu = () => {
    clearCloseTimer(programsCloseTimerRef);
    setProgramsOpen(true);
    setCommunityOpen(false);
    setProfileOpen(false);
  };

  const openCommunityMenu = () => {
    clearCloseTimer(communityCloseTimerRef);
    setCommunityOpen(true);
    setProgramsOpen(false);
    setProfileOpen(false);
  };

  const openProfileMenu = () => {
    clearCloseTimer(profileCloseTimerRef);
    setProfileOpen(true);
    setProgramsOpen(false);
    setCommunityOpen(false);
  };

  const scheduleClose = (
    timerRef: React.MutableRefObject<number | null>,
    closeMenu: React.Dispatch<React.SetStateAction<boolean>>,
  ) => {
    clearCloseTimer(timerRef);
    timerRef.current = window.setTimeout(() => {
      closeMenu(false);
    }, 120);
  };

  function PortalMenu({ anchorRef, isOpen, alignRight, onMouseEnter, onMouseLeave, children }: { anchorRef: React.RefObject<HTMLElement | null>; isOpen: boolean; alignRight?: boolean; onMouseEnter?: () => void; onMouseLeave?: () => void; children: React.ReactNode; }) {
    const [pos, setPos] = useState<{ top: number; left: number; width: number } | null>(null);

    useLayoutEffect(() => {
      if (!isOpen) return setPos(null);

      const updatePosFromEl = (elNode: HTMLElement | null) => {
        if (!elNode) return;
        const r = elNode.getBoundingClientRect();
        const top = r.bottom + window.scrollY;
        const left = r.left + window.scrollX;
        setPos({ top, left, width: r.width });
      };

      // Initial set
      updatePosFromEl(anchorRef.current);

      function onResize() {
        updatePosFromEl(anchorRef.current);
      }

      window.addEventListener("resize", onResize);
      window.addEventListener("scroll", onResize, true);
      return () => {
        window.removeEventListener("resize", onResize);
        window.removeEventListener("scroll", onResize, true);
      };
    }, [isOpen, anchorRef]);

    if (!isOpen || !pos) return null;

    const style: React.CSSProperties = {
      position: "absolute",
      top: pos.top,
      left: alignRight ? undefined : pos.left,
      right: alignRight ? Math.max(document.documentElement.clientWidth - (pos.left + pos.width), 8) : undefined,
      background: "rgba(0,0,0,0.95)",
      color: "white",
      boxShadow: "0 8px 24px rgba(0,0,0,0.12)",
      padding: 8,
      minWidth: 180,
      zIndex: 10000,
    };

    return createPortal(
      <div style={style} onMouseEnter={onMouseEnter} onMouseLeave={onMouseLeave}>
        {children}
      </div>,
      document.body,
    );
  }

  const refreshAuthState = useCallback(async (showLoading = false) => {
    if (!hasSupabaseBrowserEnv) {
      setIsSignedIn(false);
      setIsAuthChecking(false);
      return;
    }

    if (showLoading) {
      setIsAuthChecking(true);
    }

    let supabase;

    try {
      supabase = createClient();
    } catch (error) {
      console.error("[navbar] Failed to create browser Supabase client", error);
      setIsSignedIn(false);
      setIsAuthChecking(false);
      return;
    }

    try {
      const { data } = await supabase.auth.getUser();
      setIsSignedIn(Boolean(data.user));
    } catch (error) {
      console.error("[navbar] Failed to get user", error);
      setIsSignedIn(false);
    } finally {
      setIsAuthChecking(false);
    }
  }, []);

  useEffect(() => {
    if (!hasSupabaseBrowserEnv) {
      setIsSignedIn(false);
      setIsAuthChecking(false);
      return;
    }

    let supabase;

    try {
      supabase = createClient();
    } catch (error) {
      console.error("[navbar] Failed to create browser Supabase client", error);
      setIsSignedIn(false);
      setIsAuthChecking(false);
      return;
    }

    let mounted = true;

    void refreshAuthState(true);

    // Listen for auth state changes
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      if (mounted) {
        setIsSignedIn(Boolean(session?.user));
      }
    });

    return () => {
      mounted = false;
      subscription.unsubscribe();
    };
  }, [refreshAuthState]);

  useEffect(() => {
    void refreshAuthState(false);
  }, [pathname, refreshAuthState]);

  useEffect(() => {
    const handleWindowFocus = () => {
      void refreshAuthState(false);
    };

    const handleVisibilityChange = () => {
      if (!document.hidden) {
        void refreshAuthState(false);
      }
    };

    window.addEventListener("focus", handleWindowFocus);
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      window.removeEventListener("focus", handleWindowFocus);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [refreshAuthState]);

  useEffect(() => {
    // Close mobile menu if user signs out
    if (!isSignedIn && mobileMenuOpen) {
      setMobileMenuOpen(false);
      setProgramsMobileOpen(false);
      setCommunityMobileOpen(false);
      setProfileMobileOpen(false);
      setActiveFor(null);
    }
  }, [isSignedIn, mobileMenuOpen]);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      const target = e.target as Node;

      if (programsRef.current && !programsRef.current.contains(target)) {
        setProgramsOpen(false);
      }
      if (communityRef.current && !communityRef.current.contains(target)) {
        setCommunityOpen(false);
      }
      if (profileRef.current && !profileRef.current.contains(target)) {
        setProfileOpen(false);
      }
      if (
        mobileMenuOpen &&
        mobileMenuRef.current &&
        !mobileMenuRef.current.contains(target) &&
        mobileMenuButtonRef.current &&
        !mobileMenuButtonRef.current.contains(target)
      ) {
        setMobileMenuOpen(false);
        setProgramsMobileOpen(false);
        setCommunityMobileOpen(false);
        setProfileMobileOpen(false);
        setActiveFor(null);
      }
    }
    document.addEventListener("click", onDoc);
    return () => document.removeEventListener("click", onDoc);
  }, [mobileMenuOpen]);

  useEffect(() => {
    return () => {
      clearCloseTimer(programsCloseTimerRef);
      clearCloseTimer(communityCloseTimerRef);
      clearCloseTimer(profileCloseTimerRef);
    };
  }, []);

  // Responsive detection for mobile menu
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 768px)');
    const set = () => {
      setIsMobile(!!mq.matches);
      if (!mq.matches) {
        setMobileMenuOpen(false);
        setProgramsMobileOpen(false);
        setCommunityMobileOpen(false);
      }
    };
    set();
    const handler = () => set();
    mq.addEventListener?.('change', handler);
    window.addEventListener('resize', handler);
    return () => {
      mq.removeEventListener?.('change', handler);
      window.removeEventListener('resize', handler);
    };
  }, []);

  return (
    <header style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', position: 'sticky', top: 0, zIndex: 1000, backgroundColor: '#000' }}>
      <div style={{ display: 'flex', alignItems: 'center', padding: '0 60px', whiteSpace: 'nowrap', height: 80, color: 'white' }}>
        {/* Left: logo (hidden on mobile, moved to center) */}
        <div style={{ flex: '0 0 auto' }}>
          {!isMobile && (
            <Link
              href="/"
              style={{
                ...navItemBase,
                fontWeight: 700,
                fontSize: 18,
                textDecoration: 'none',
                color: aiHmActive ? 'white' : undefined,
                boxShadow: aiHmActive ? '0 18px 60px rgba(0,0,0,0.30)' : undefined,
                backgroundColor: aiHmActive ? 'rgba(255, 255, 255, 0)' : undefined,
                borderRadius: aiHmActive ? 10 : undefined,
              }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.transform = 'translateY(-2px)'; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.transform = ''; }}
            >
              AIHM
            </Link>
          )}
        </div>

        {/* Center: main nav - centered (on mobile: logo centered) */}
        <div style={{ flex: '1 1 auto', display: 'flex', justifyContent: 'center' }}>
          {!isMobile && isSignedIn ? (
            <nav style={{ display: 'flex', gap: 28, alignItems: 'center', flexWrap: 'nowrap' }}>
              <Link
                href="/workouts"
                style={{
                  ...navItemBase,
                  boxShadow: startActive ? '0 18px 60px rgba(0,0,0,0.30)' : undefined,
                  backgroundColor: startActive ? 'rgba(255,255,255,0.05)' : undefined,
                  borderRadius: startActive ? 10 : undefined,
                  color: startActive ? 'white' : undefined,
                }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.transform = 'translateY(-2px)'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.transform = ''; }}
              >
                Start Workout
              </Link>

              <div
                ref={programsRef}
                style={{ position: 'relative' }}
                onMouseEnter={openProgramsMenu}
                onMouseLeave={() => scheduleClose(programsCloseTimerRef, setProgramsOpen)}
              >
                <button
                  ref={programsBtnRef}
                  onClick={() => setProgramsOpen(v => {
                    const next = !v;
                    if (next) {
                      openProgramsMenu();
                    }
                    return next;
                  })}
                  style={{
                      ...navItemBase,
                      boxShadow: isProgramsActive ? '0 18px 60px rgba(0,0,0,0.30)' : undefined,
                      backgroundColor: isProgramsActive ? 'rgba(255,255,255,0.05)' : undefined,
                      borderRadius: isProgramsActive ? 10 : undefined,
                    }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.transform = 'translateY(-2px)'; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.transform = ''; }}
                >
                  Programs ▾
                </button>
                <PortalMenu
                  anchorRef={programsBtnRef}
                  isOpen={programsOpen}
                  onMouseEnter={openProgramsMenu}
                  onMouseLeave={() => scheduleClose(programsCloseTimerRef, setProgramsOpen)}
                >
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <Link href="/browsePrograms" onClick={() => setProgramsOpen(false)} style={{ whiteSpace: 'nowrap', color: 'inherit' }}>Browse Programs</Link>
                    <Link href="/programs" onClick={() => setProgramsOpen(false)} style={{ whiteSpace: 'nowrap', color: 'inherit' }}>Current Programs</Link>
                    <Link href="/progress" onClick={() => setProgramsOpen(false)} style={{ whiteSpace: 'nowrap', color: 'inherit' }}>Progress</Link>
                  </div>
                </PortalMenu>
              </div>

              <div
                ref={communityRef}
                style={{ position: 'relative' }}
                onMouseEnter={openCommunityMenu}
                onMouseLeave={() => scheduleClose(communityCloseTimerRef, setCommunityOpen)}
              >
                <button
                  ref={communityBtnRef}
                  onClick={() => setCommunityOpen(v => {
                    const next = !v;
                    if (next) {
                      openCommunityMenu();
                    }
                    return next;
                  })}
                  style={{
                      ...navItemBase,
                      boxShadow: communityActive ? '0 18px 60px rgba(0,0,0,0.30)' : undefined,
                      backgroundColor: communityActive ? 'rgba(255,255,255,0.05)' : undefined,
                      borderRadius: communityActive ? 10 : undefined,
                    }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.transform = 'translateY(-2px)'; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.transform = ''; }}
                >
                  Community ▾
                </button>
                <PortalMenu
                  anchorRef={communityBtnRef}
                  isOpen={communityOpen}
                  onMouseEnter={openCommunityMenu}
                  onMouseLeave={() => scheduleClose(communityCloseTimerRef, setCommunityOpen)}
                >
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <Link href="/community" onClick={() => setCommunityOpen(false)} style={{ whiteSpace: 'nowrap', color: 'inherit' }}>Forums & Challenges</Link>
                    <Link href="/friends" onClick={() => setCommunityOpen(false)} style={{ whiteSpace: 'nowrap', color: 'inherit' }}>Friends</Link>
                  </div>
                </PortalMenu>
              </div>
              <Link
                href="/notifications"
                style={{
                  ...navItemBase,
                  boxShadow: notificationsActive ? '0 18px 60px rgba(0,0,0,0.30)' : undefined,
                  backgroundColor: notificationsActive ? 'rgba(255,255,255,0.05)' : undefined,
                  borderRadius: notificationsActive ? 10 : undefined,
                }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.transform = 'translateY(-2px)'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.transform = ''; }}
              >
                Notifications
              </Link>
            </nav>
          ) : null}
        </div>

        {/* Right: notifications + profile (and hamburger on mobile) */}
        <div style={{ flex: '0 0 auto', display: 'flex', gap: 20, alignItems: 'center' }}>
          {isMobile && !isAuthChecking && isSignedIn ? (
            <button
              ref={mobileMenuButtonRef}
              aria-label="Open menu"
              onClick={() => setMobileMenuOpen(v => !v)}
              style={{
                whiteSpace: 'nowrap',
                backgroundColor: '#000',
                color: 'white',
                border: 'none',
                appearance: 'none',
                WebkitAppearance: 'none',
                colorScheme: 'dark',
                fontSize: 24,
                lineHeight: 1,
                padding: 0,
              }}
            >
              ☰
            </button>
          ) : null}

          {!isAuthChecking && !isSignedIn ? (
            <div style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
              <Link
                href="/auth/login"
                style={{
                  ...navItemBase,
                  textDecoration: 'none',
                  color: 'white',
                }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.transform = 'translateY(-2px)'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.transform = ''; }}
              >
                Sign in
              </Link>
              <Link
                href="/auth/sign-up"
                style={{
                  ...navItemBase,
                  textDecoration: 'none',
                  color: 'black',
                  backgroundColor: 'white',
                  borderRadius: 999,
                  padding: '8px 14px',
                  fontWeight: 600,
                }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.transform = 'translateY(-2px)'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.transform = ''; }}
              >
                Sign up
              </Link>
            </div>
          ) : null}

          {!isMobile && isSignedIn ? (
            <div
              ref={profileRef}
              style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 16 }}
              onMouseEnter={openProfileMenu}
              onMouseLeave={() => scheduleClose(profileCloseTimerRef, setProfileOpen)}
            >
              <button
                ref={profileBtnRef}
                onClick={() => setProfileOpen(v => {
                  const next = !v;
                  if (next) {
                    openProfileMenu();
                  }
                  return next;
                })}
                style={{
                  ...navItemBase,
                  transition: 'transform 120ms ease, box-shadow 180ms ease',
                  transform: '',
                  boxShadow: profileActive ? '0 18px 60px rgba(0,0,0,0.30)' : undefined,
                  backgroundColor: profileActive ? 'rgba(255,255,255,0.05)' : undefined,
                  borderRadius: profileActive ? 10 : undefined,
                }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.transform = 'translateY(-2px)'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.transform = ''; }}
              >
                Profile ▾
              </button>
              <form action={logoutAction}>
                <button
                  type="submit"
                  style={{
                    ...navItemBase,
                    ...signOutButtonBase,
                    color: 'rgba(255,255,255,0.7)',
                    fontSize: 14,
                  }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.color = 'white'; (e.currentTarget as HTMLButtonElement).style.transform = 'translateY(-2px)'; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.color = 'rgba(255,255,255,0.7)'; (e.currentTarget as HTMLButtonElement).style.transform = ''; }}
                >
                  Sign Out
                </button>
              </form>
              <PortalMenu
                anchorRef={profileBtnRef}
                isOpen={profileOpen}
                alignRight
                onMouseEnter={openProfileMenu}
                onMouseLeave={() => scheduleClose(profileCloseTimerRef, setProfileOpen)}
              >
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <Link href={isSignedIn ? "/profile" : "/auth/login"} onClick={() => setProfileOpen(false)} style={{ whiteSpace: 'nowrap', color: 'inherit' }}>{isSignedIn ? 'Profile Settings' : 'Sign in'}</Link>
                  <Link href="/help" onClick={() => setProfileOpen(false)} style={{ whiteSpace: 'nowrap', color: 'inherit' }}>Help / Docs</Link>
                  {isSignedIn ? (
                    <form action={logoutAction}>
                      <button
                        type="submit"
                        onClick={() => setProfileOpen(false)}
                        style={{ ...signOutButtonBase, whiteSpace: 'nowrap', color: 'inherit' }}
                      >
                        Sign out
                      </button>
                    </form>
                  ) : null}
                </div>
              </PortalMenu>
            </div>
          ) : null}
        </div>
      </div>

      {/* Mobile menu panel (simple vertical menu) */}
      {isMobile && isSignedIn && mobileMenuOpen && (
        <div ref={mobileMenuRef} style={{ position: 'absolute', top: '100%', left: 0, right: 0, backgroundColor: '#000', color: 'white', padding: 12, boxShadow: '0 6px 18px rgba(0,0,0,0.12)', zIndex: 9999, colorScheme: 'dark' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {isSignedIn ? (
              <>
                <Link
                  href="/workouts"
                  onClick={() => { setMobileMenuOpen(false); setActiveFor('workout'); }}
                  style={{ whiteSpace: 'nowrap', color: activeMobileTop && activeMobileTop !== 'workout' ? 'rgba(255,255,255,0.6)' : 'white', transition: 'color 150ms ease' }}
                >
                  Start Workout
                </Link>

                <div>
                  <button
                    onClick={() => { toggleProgramsMobile(); setActiveFor(programsMobileOpen ? null : 'programs'); }}
                    style={{ width: '100%', textAlign: 'left', color: activeMobileTop === 'programs' ? 'white' : 'rgba(255,255,255,0.6)', backgroundColor: 'transparent', border: 'none', transition: 'color 180ms ease', colorScheme: 'dark' }}
                  >
                    Programs ▾
                  </button>

                  <div style={{ overflow: 'hidden', maxHeight: programsMobileOpen ? 240 : 0, opacity: programsMobileOpen ? 1 : 0, transition: 'max-height 220ms ease, opacity 180ms ease' }}>
                    <div style={{ paddingLeft: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
                      <Link href="/browsePrograms" onClick={() => { setMobileMenuOpen(false); setProgramsMobileOpen(false); setActiveFor(null); }} style={{ color: 'white' }}>Browse Programs</Link>
                      <Link href="/programs" onClick={() => { setMobileMenuOpen(false); setProgramsMobileOpen(false); setActiveFor(null); }} style={{ color: 'white' }}>Current Programs</Link>
                      <Link href="/progress" onClick={() => { setMobileMenuOpen(false); setProgramsMobileOpen(false); setActiveFor(null); }} style={{ color: 'white' }}>Progress</Link>
                    </div>
                  </div>
                </div>

                <div>
                  <button
                    onClick={() => { toggleCommunityMobile(); setActiveFor(communityMobileOpen ? null : 'community'); }}
                    style={{ width: '100%', textAlign: 'left', color: activeMobileTop === 'community' ? 'white' : 'rgba(255,255,255,0.6)', backgroundColor: 'transparent', border: 'none', transition: 'color 180ms ease', colorScheme: 'dark' }}
                  >
                    Community ▾
                  </button>
                  <div style={{ overflow: 'hidden', maxHeight: communityMobileOpen ? 200 : 0, opacity: communityMobileOpen ? 1 : 0, transition: 'max-height 220ms ease, opacity 180ms ease' }}>
                    <div style={{ paddingLeft: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
                      <Link href="/community" onClick={() => { setMobileMenuOpen(false); setCommunityMobileOpen(false); setActiveFor(null); }} style={{ color: 'white' }}>Forums & Challenges</Link>
                      <Link href="/friends" onClick={() => { setMobileMenuOpen(false); setCommunityMobileOpen(false); setActiveFor(null); }} style={{ color: 'white' }}>Friends</Link>
                    </div>
                  </div>
                </div>
                <Link
                  href="/notifications"
                  onClick={() => { setMobileMenuOpen(false); setActiveFor('notifications'); }}
                  style={{ color: activeMobileTop === 'notifications' ? 'white' : 'rgba(255,255,255,0.6)', transition: 'color 180ms ease' }}
                >
                  Notifications
                </Link>

                <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 10 }}>
                  <button
                    onClick={() => { toggleProfileMobile(); setActiveFor(profileMobileOpen ? null : 'profile'); }}
                    style={{ width: '100%', textAlign: 'left', color: activeMobileTop === 'profile' ? 'white' : 'rgba(255,255,255,0.6)', backgroundColor: 'transparent', border: 'none', transition: 'color 180ms ease', colorScheme: 'dark' }}
                  >
                    Profile ▾
                  </button>
                  <div style={{ overflow: 'hidden', maxHeight: profileMobileOpen ? 160 : 0, opacity: profileMobileOpen ? 1 : 0, transition: 'max-height 220ms ease, opacity 180ms ease' }}>
                    <div style={{ paddingLeft: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
                      <Link href="/profile" onClick={() => { setMobileMenuOpen(false); setProfileMobileOpen(false); setActiveFor(null); }} style={{ color: 'white' }}>Profile Settings</Link>
                      <Link href="/help" onClick={() => { setMobileMenuOpen(false); setProfileMobileOpen(false); setActiveFor(null); }} style={{ color: 'white' }}>Help / Docs</Link>
                    </div>
                  </div>
                </div>
                <form action={logoutAction}>
                  <button
                    type="submit"
                    onClick={() => { setMobileMenuOpen(false); setActiveFor(null); }}
                    style={{ ...signOutButtonBase, color: 'rgba(255,255,255,0.6)', fontWeight: 500, transition: 'color 150ms ease' }}
                  >
                    Sign Out
                  </button>
                </form>
              </>
            ) : null}
          </div>
        </div>
      )}
    </header>
  );
}
