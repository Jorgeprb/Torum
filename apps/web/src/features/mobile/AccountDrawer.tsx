import { useEffect, useState } from "react";
import {
  Activity,
  BarChart3,
  CalendarClock,
  Check,
  FlaskConical,
  Gauge,
  History,
  Pencil,
  Plus,
  RefreshCw,
  Server,
  Settings,
  Trash2,
  TrendingUp,
  X,
  type LucideIcon
} from "lucide-react";

import {
  deleteSavedMt5Account,
  discoverMt5Accounts,
  getSavedMt5Accounts,
  renameSavedMt5Account,
  saveMt5Account,
  switchMt5Account,
  type MT5DiscoveredAccount,
  type MT5Status,
  type SavedMT5Account
} from "../../services/market";

export type MobileView = "chart" | "performance" | "strategies" | "simulator" | "indicators" | "settings" | "history" | "news";

interface AccountDrawerProps {
  activeView: MobileView;
  mt5Status: MT5Status | null;
  onAccountChanged?: (status: MT5Status) => void | Promise<void>;
  onClose: () => void;
  onNavigate: (view: MobileView) => void;
  open: boolean;
}

export const accountNavItems: Array<{ id: MobileView; label: string; icon: LucideIcon }> = [
  { id: "chart", label: "Grafico", icon: BarChart3 },
  { id: "performance", label: "Rentabilidad", icon: TrendingUp },
  { id: "history", label: "Historial", icon: History },
  { id: "news", label: "Noticias", icon: CalendarClock },
  { id: "strategies", label: "Estrategias", icon: Activity },
  { id: "simulator", label: "Simulador", icon: FlaskConical },
  { id: "indicators", label: "Indicadores", icon: Gauge },
  { id: "settings", label: "Ajustes", icon: Settings }
];

const drawerNavItems = accountNavItems.filter(
  (item) => item.id !== "simulator" && item.id !== "indicators"
);

function accountMatches(status: MT5Status | null, saved: SavedMT5Account): boolean {
  const active = status?.account;
  return Boolean(
    active?.login === saved.login &&
      (active.server ?? "").trim().toLowerCase() === saved.server.trim().toLowerCase()
  );
}

function discoveredKey(account: Pick<MT5DiscoveredAccount, "login" | "server">): string {
  return `${account.login}@${account.server.trim().toLowerCase()}`;
}

export function AccountDrawer({
  activeView,
  mt5Status,
  onAccountChanged,
  onClose,
  onNavigate,
  open
}: AccountDrawerProps) {
  const account = mt5Status?.account;
  const [savedAccounts, setSavedAccounts] = useState<SavedMT5Account[]>([]);
  const [accountsLoading, setAccountsLoading] = useState(false);
  const [accountsError, setAccountsError] = useState<string | null>(null);
  const [showAddAccount, setShowAddAccount] = useState(false);
  const [discoveredAccounts, setDiscoveredAccounts] = useState<MT5DiscoveredAccount[]>([]);
  const [discoveringAccounts, setDiscoveringAccounts] = useState(false);
  const [addingAccountKey, setAddingAccountKey] = useState<string | null>(null);
  const [switchCandidate, setSwitchCandidate] = useState<SavedMT5Account | null>(null);
  const [switchingAccountId, setSwitchingAccountId] = useState<number | null>(null);
  const [deleteCandidate, setDeleteCandidate] = useState<SavedMT5Account | null>(null);
  const [deletingAccountId, setDeletingAccountId] = useState<number | null>(null);
  const [aliasCandidate, setAliasCandidate] = useState<SavedMT5Account | null>(null);
  const [aliasDraft, setAliasDraft] = useState("");
  const [aliasSavingId, setAliasSavingId] = useState<number | null>(null);

  async function refreshAccounts(): Promise<void> {
    setAccountsLoading(true);
    setAccountsError(null);
    try {
      setSavedAccounts(await getSavedMt5Accounts());
    } catch (error) {
      setAccountsError(error instanceof Error ? error.message : "No se pudieron cargar las cuentas MT5");
    } finally {
      setAccountsLoading(false);
    }
  }

  async function refreshDiscoveredAccounts(): Promise<void> {
    setDiscoveringAccounts(true);
    setAccountsError(null);
    try {
      setDiscoveredAccounts(await discoverMt5Accounts());
    } catch (error) {
      setAccountsError(error instanceof Error ? error.message : "No se pudieron consultar las cuentas del terminal MT5");
      setDiscoveredAccounts([]);
    } finally {
      setDiscoveringAccounts(false);
    }
  }

  async function openAddAccount(): Promise<void> {
    setShowAddAccount(true);
    await refreshDiscoveredAccounts();
  }

  useEffect(() => {
    if (!open) return;
    void refreshAccounts();
  }, [open, mt5Status?.account?.login, mt5Status?.account?.server]);

  async function addDiscoveredAccount(candidate: MT5DiscoveredAccount): Promise<void> {
    if (candidate.already_saved) return;
    const key = discoveredKey(candidate);
    setAddingAccountKey(key);
    setAccountsError(null);
    try {
      const saved = await saveMt5Account({ login: candidate.login, server: candidate.server });
      setDiscoveredAccounts((current) =>
        current.map((item) =>
          discoveredKey(item) === key ? { ...item, already_saved: true } : item
        )
      );
      await refreshAccounts();
      setShowAddAccount(false);
      openAliasEditor(saved);
    } catch (error) {
      setAccountsError(error instanceof Error ? error.message : "No se pudo guardar la cuenta MT5");
    } finally {
      setAddingAccountKey(null);
    }
  }

  async function confirmDelete(): Promise<void> {
    if (!deleteCandidate || accountMatches(mt5Status, deleteCandidate)) return;
    setDeletingAccountId(deleteCandidate.id);
    setAccountsError(null);
    try {
      await deleteSavedMt5Account(deleteCandidate.id);
      setDeleteCandidate(null);
      await refreshAccounts();
      if (showAddAccount) await refreshDiscoveredAccounts();
    } catch (error) {
      setAccountsError(error instanceof Error ? error.message : "No se pudo eliminar la cuenta");
    } finally {
      setDeletingAccountId(null);
    }
  }

  function openAliasEditor(saved: SavedMT5Account): void {
    setAliasCandidate(saved);
    setAliasDraft(saved.alias);
    setAccountsError(null);
  }

  async function confirmAlias(): Promise<void> {
    if (!aliasCandidate) return;
    const alias = aliasDraft.trim();
    if (!alias) {
      setAccountsError("El alias no puede estar vacío");
      return;
    }
    setAliasSavingId(aliasCandidate.id);
    setAccountsError(null);
    try {
      const updated = await renameSavedMt5Account(aliasCandidate.id, alias);
      setSavedAccounts((current) => current.map((item) => item.id === updated.id ? updated : item));
      setAliasCandidate(null);
      setAliasDraft("");
    } catch (error) {
      setAccountsError(error instanceof Error ? error.message : "No se pudo cambiar el alias");
    } finally {
      setAliasSavingId(null);
    }
  }

  async function confirmSwitch(): Promise<void> {
    if (!switchCandidate) return;
    setSwitchingAccountId(switchCandidate.id);
    setAccountsError(null);
    try {
      const result = await switchMt5Account(switchCandidate.id);
      setSwitchCandidate(null);
      setSavedAccounts((current) =>
        current.map((item) => ({ ...item, active: item.id === result.account.id }))
      );
      await onAccountChanged?.(result.mt5_status);
      await refreshAccounts();
    } catch (error) {
      setAccountsError(error instanceof Error ? error.message : "No se pudo cambiar la cuenta MT5");
      setSwitchCandidate(null);
    } finally {
      setSwitchingAccountId(null);
    }
  }

  return (
    <>
      <div className={open ? "drawer-backdrop drawer-backdrop--open" : "drawer-backdrop"} onClick={onClose} />
      <aside className={open ? "account-drawer account-drawer--open" : "account-drawer"} aria-hidden={!open}>
        <div className="account-drawer__header">
          <div>
            <p className="eyebrow">Torum</p>
            <h2>Cuenta</h2>
          </div>
          <button aria-label="Cerrar menu" className="mobile-icon-button" type="button" onClick={onClose}>
            <X size={22} />
          </button>
        </div>

        <section className="account-card mt5-account-manager">
          <div className="mt5-account-manager__heading">
            <div>
              <p className="eyebrow">MetaTrader 5</p>
              <strong>Cambiar cuenta</strong>
            </div>
            <button
              aria-label="Actualizar cuentas"
              className="mt5-account-icon-button"
              disabled={accountsLoading}
              type="button"
              onClick={() => void refreshAccounts()}
            >
              <RefreshCw className={accountsLoading ? "spin" : undefined} size={17} />
            </button>
          </div>

          {savedAccounts.length > 0 ? (
            <div className="mt5-account-list">
              {savedAccounts.map((saved) => {
                const active = accountMatches(mt5Status, saved) || saved.active;
                return (
                  <div className={active ? "mt5-account-row mt5-account-row--active" : "mt5-account-row"} key={saved.id}>
                    <button
                      className="mt5-account-row__main"
                      disabled={active || switchingAccountId !== null || deletingAccountId !== null}
                      type="button"
                      onClick={() => setSwitchCandidate(saved)}
                    >
                      <span className="mt5-account-row__status">{active ? <Check size={16} /> : <Server size={16} />}</span>
                      <span>
                        <strong>{saved.alias}</strong>
                        <small>{saved.login} · {saved.server}</small>
                      </span>
                      <em>{saved.last_trade_mode ?? (active ? mt5Status?.account_trade_mode : "")}</em>
                    </button>
                    <div className="mt5-account-row__actions">
                      <button
                        aria-label={`Cambiar alias de ${saved.alias}`}
                        className="mt5-account-row__edit"
                        disabled={accountsLoading || switchingAccountId !== null || deletingAccountId !== null || aliasSavingId !== null}
                        type="button"
                        onClick={() => openAliasEditor(saved)}
                      >
                        <Pencil size={14} />
                      </button>
                      {!active ? (
                        <button
                          aria-label={`Eliminar ${saved.alias}`}
                          className="mt5-account-row__delete"
                          disabled={accountsLoading || switchingAccountId !== null || deletingAccountId !== null || aliasSavingId !== null}
                          type="button"
                          onClick={() => setDeleteCandidate(saved)}
                        >
                          <Trash2 size={15} />
                        </button>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="mt5-account-help">Todavía no has guardado cuentas en Torum.</p>
          )}

          <button className="mt5-account-secondary-button" disabled={discoveringAccounts} type="button" onClick={() => void openAddAccount()}>
            <Plus size={16} /> Añadir cuenta
          </button>

          {accountsError ? <p className="form-error">{accountsError}</p> : null}
        </section>

        <nav className="drawer-nav" aria-label="Navegacion movil">
          {drawerNavItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                className={activeView === item.id ? "drawer-nav__item drawer-nav__item--active" : "drawer-nav__item"}
                key={item.id}
                type="button"
                onClick={() => {
                  onNavigate(item.id);
                  onClose();
                }}
              >
                <Icon size={18} />
                {item.label}
              </button>
            );
          })}
        </nav>
      </aside>

      {showAddAccount ? (
        <div className="mt5-account-confirm-backdrop" role="presentation">
          <section aria-labelledby="mt5-account-add-title" aria-modal="true" className="mt5-account-confirm" role="dialog">
            <div className="mt5-account-manager__heading">
              <div>
                <p className="eyebrow">MetaTrader 5</p>
                <h2 id="mt5-account-add-title">Añadir cuenta</h2>
              </div>
              <button
                aria-label="Volver a buscar cuentas"
                className="mt5-account-icon-button"
                disabled={discoveringAccounts || addingAccountKey !== null}
                type="button"
                onClick={() => void refreshDiscoveredAccounts()}
              >
                <RefreshCw className={discoveringAccounts ? "spin" : undefined} size={17} />
              </button>
            </div>

            <p className="mt5-account-help">
              Cuentas detectadas en el MT5 de este ordenador. Torum no lee ni guarda contraseñas.
            </p>

            {discoveringAccounts ? (
              <div className="mt5-account-discovery-empty"><RefreshCw className="spin" size={18} /> Buscando cuentas…</div>
            ) : discoveredAccounts.length > 0 ? (
              <div className="mt5-account-list mt5-account-discovery-list">
                {discoveredAccounts.map((candidate) => {
                  const key = discoveredKey(candidate);
                  const adding = addingAccountKey === key;
                  return (
                    <div className={candidate.active ? "mt5-account-row mt5-account-row--active" : "mt5-account-row"} key={key}>
                      <div className="mt5-account-row__main mt5-account-row__main--static">
                        <span className="mt5-account-row__status">{candidate.active ? <Check size={16} /> : <Server size={16} />}</span>
                        <span>
                          <strong>{candidate.login}</strong>
                          <small>{candidate.server}</small>
                        </span>
                        <em>{candidate.active ? "ACTIVA" : "MT5"}</em>
                      </div>
                      <button
                        className={candidate.already_saved ? "mt5-account-discovery-action mt5-account-discovery-action--saved" : "mt5-account-discovery-action"}
                        disabled={candidate.already_saved || addingAccountKey !== null}
                        type="button"
                        onClick={() => void addDiscoveredAccount(candidate)}
                      >
                        {candidate.already_saved ? "Guardada" : adding ? "Añadiendo…" : "Añadir"}
                      </button>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="mt5-account-discovery-empty">
                No se encontraron cuentas. Abre/inicia sesión en una cuenta desde ese terminal MT5 y vuelve a buscar.
              </div>
            )}

            {accountsError ? <p className="form-error">{accountsError}</p> : null}
            <div className="mt5-account-form__actions">
              <button className="mt5-account-secondary-button" disabled={addingAccountKey !== null} type="button" onClick={() => setShowAddAccount(false)}>
                Cerrar
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {aliasCandidate ? (
        <div className="mt5-account-confirm-backdrop" role="presentation">
          <section aria-labelledby="mt5-account-alias-title" aria-modal="true" className="mt5-account-confirm" role="dialog">
            <p className="eyebrow">Personalizar cuenta</p>
            <h2 id="mt5-account-alias-title">Alias de la cuenta</h2>
            <p className="mt5-account-help">
              Puedes usar texto, símbolos y emojis. El alias solo cambia cómo aparece esta cuenta dentro de Torum.
            </p>
            <label className="mt5-account-alias-field">
              <span>Alias</span>
              <input
                autoFocus
                maxLength={120}
                type="text"
                value={aliasDraft}
                onChange={(event) => setAliasDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void confirmAlias();
                }}
                placeholder="Ej. 🚀 Cuenta principal"
              />
            </label>
            <div className="mt5-account-alias-preview">
              <span>Vista previa</span>
              <strong>{aliasDraft.trim() || "Sin alias"}</strong>
              <small>{aliasCandidate.login} · {aliasCandidate.server}</small>
            </div>
            {accountsError ? <p className="form-error">{accountsError}</p> : null}
            <div className="mt5-account-form__actions">
              <button className="mt5-account-secondary-button" disabled={aliasSavingId !== null} type="button" onClick={() => { setAliasCandidate(null); setAliasDraft(""); }}>
                Cancelar
              </button>
              <button className="primary-button" disabled={aliasSavingId !== null || !aliasDraft.trim()} type="button" onClick={() => void confirmAlias()}>
                {aliasSavingId !== null ? "Guardando…" : "Guardar alias"}
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {deleteCandidate ? (
        <div className="mt5-account-confirm-backdrop" role="presentation">
          <section aria-labelledby="mt5-account-delete-title" aria-modal="true" className="mt5-account-confirm" role="dialog">
            <p className="eyebrow">Confirmación</p>
            <h2 id="mt5-account-delete-title">Borrar cuenta de Torum</h2>
            <p>
              Vas a eliminar <strong>{deleteCandidate.alias}</strong> ({deleteCandidate.login} · {deleteCandidate.server}) de la lista de Torum.
            </p>
            <p className="mt5-account-help">
              No se elimina del terminal MetaTrader 5, no se borran credenciales del ordenador y no se cierra ninguna posición.
            </p>
            <div className="mt5-account-form__actions">
              <button className="mt5-account-secondary-button" disabled={deletingAccountId !== null} type="button" onClick={() => setDeleteCandidate(null)}>
                Cancelar
              </button>
              <button className="mt5-account-danger-button" disabled={deletingAccountId !== null} type="button" onClick={() => void confirmDelete()}>
                {deletingAccountId !== null ? "Eliminando…" : "Borrar cuenta"}
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {switchCandidate ? (
        <div className="mt5-account-confirm-backdrop" role="presentation">
          <section aria-labelledby="mt5-account-switch-title" aria-modal="true" className="mt5-account-confirm" role="dialog">
            <p className="eyebrow">Confirmación</p>
            <h2 id="mt5-account-switch-title">Cambiar cuenta MT5</h2>
            <p>
              Vas a cambiar de <strong>{account?.login ?? "--"} · {account?.server ?? "--"}</strong> a{" "}
              <strong>{switchCandidate.login} · {switchCandidate.server}</strong>.
            </p>
            {switchCandidate.last_trade_mode === "REAL" ? (
              <p className="mt5-account-confirm__warning">La cuenta seleccionada es REAL. Las nuevas operaciones se enviarán a esa cuenta si el trading LIVE está habilitado.</p>
            ) : null}
            <p className="mt5-account-help">Las posiciones de la cuenta anterior no se cierran. Torum cambiará la sesión activa del terminal y resincronizará posiciones, riesgo e historial.</p>
            <div className="mt5-account-form__actions">
              <button className="mt5-account-secondary-button" disabled={switchingAccountId !== null} type="button" onClick={() => setSwitchCandidate(null)}>Cancelar</button>
              <button className="primary-button" disabled={switchingAccountId !== null} type="button" onClick={() => void confirmSwitch()}>
                {switchingAccountId !== null ? "Cambiando…" : "Confirmar cambio"}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </>
  );
}
