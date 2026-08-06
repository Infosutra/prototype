import React, { useEffect, useState } from "react";
import {
  getGetSettingsQueryKey,
  useGetSettings,
  useSendDailyReport,
  useTestKoboConnection,
  useTestSmtpConnection,
  useUpdateSettings,
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Layout } from "@/components/layout/Layout";
import { Header } from "@/components/layout/Header";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Save, CheckCircle2, Server, Mail, Settings2, AlertCircle } from "lucide-react";
import { useStudy } from "@/components/study/StudyProvider";

function parseRecipientInput(value: string): string[] {
  return [...new Set(value.split(/[,;\n]+/).map((item) => item.trim()).filter(Boolean))];
}

export default function Settings() {
  const queryClient = useQueryClient();
  const settingsQuery = useGetSettings();
  const { studies, activeStudyId } = useStudy();
  const [activeTab, setActiveTab] = useState("kobo");

  const [serverUrl, setServerUrl] = useState("https://kf.kobotoolbox.org");
  const [apiToken, setApiToken] = useState("");
  const [autoSync, setAutoSync] = useState(false);
  const [syncIntervalHours, setSyncIntervalHours] = useState("24");

  const [smtpHost, setSmtpHost] = useState("smtp-relay.brevo.com");
  const [smtpPort, setSmtpPort] = useState("587");
  const [smtpUsername, setSmtpUsername] = useState("");
  const [smtpPassword, setSmtpPassword] = useState("");
  const [smtpFromName, setSmtpFromName] = useState("Infosutra");
  const [smtpFromEmail, setSmtpFromEmail] = useState("");
  const [smtpUseTls, setSmtpUseTls] = useState(true);

  const [dailyReportEnabled, setDailyReportEnabled] = useState(false);
  const [dailyReportTime, setDailyReportTime] = useState("21:00");
  const [dailyReportRecipients, setDailyReportRecipients] = useState("");

  const [dqaDailyEnabled, setDqaDailyEnabled] = useState(false);
  const [dqaDailyTime, setDqaDailyTime] = useState("21:30");
  const [dqaDailyRecipients, setDqaDailyRecipients] = useState("");
  const [dqaDailyStudyId, setDqaDailyStudyId] = useState("");
  const [dqaDailySending, setDqaDailySending] = useState(false);

  const [aiEnabled, setAiEnabled] = useState(false);
  const [aiApiKey, setAiApiKey] = useState("");
  const [aiModel, setAiModel] = useState("nvidia/nemotron-3-super-120b-a12b:free");
  const [aiBaseUrl, setAiBaseUrl] = useState("https://openrouter.ai/api/v1");

  const [feedback, setFeedback] = useState<{ success: boolean; message: string } | null>(null);

  const updateSettings = useUpdateSettings({
    mutation: {
      onSuccess: (settings) => {
        setApiToken(settings.kobo.apiToken);
        setSmtpPassword(settings.smtp.password);
        setDailyReportEnabled(settings.dailyReport.enabled);
        setDailyReportTime(settings.dailyReport.sendTime || "21:00");
        setDailyReportRecipients(settings.dailyReport.recipients.join("\n"));
        const extended = settings as typeof settings & {
          dqaDaily?: {
            enabled: boolean;
            sendTime: string;
            recipients: string[];
            studyId?: string | null;
          };
          general?: {
            aiEnabled?: boolean;
            aiApiKey?: string;
            aiModel?: string;
            aiBaseUrl?: string;
          };
        };
        if (extended.dqaDaily) {
          setDqaDailyEnabled(extended.dqaDaily.enabled);
          setDqaDailyTime(extended.dqaDaily.sendTime || "21:30");
          setDqaDailyRecipients((extended.dqaDaily.recipients || []).join("\n"));
          setDqaDailyStudyId(extended.dqaDaily.studyId || "");
        }
        if (extended.general) {
          setAiEnabled(Boolean(extended.general.aiEnabled));
          setAiApiKey(extended.general.aiApiKey || "");
          setAiModel(
            extended.general.aiModel || "nvidia/nemotron-3-super-120b-a12b:free",
          );
          setAiBaseUrl(extended.general.aiBaseUrl || "https://openrouter.ai/api/v1");
        }
        setFeedback({
          success: true,
          message:
            activeTab === "smtp"
              ? "Email settings saved."
              : activeTab === "general"
                ? "General / AI settings saved."
                : "Kobo settings saved and connection verified.",
        });
        queryClient.invalidateQueries({ queryKey: getGetSettingsQueryKey() });
      },
      onError: (error) => setFeedback({ success: false, message: error.message }),
    },
  });

  const testKoboConnection = useTestKoboConnection({
    mutation: {
      onSuccess: (result) => setFeedback({ success: result.success, message: result.details ?? result.message }),
      onError: (error) => setFeedback({ success: false, message: error.message }),
    },
  });

  const testSmtpConnection = useTestSmtpConnection({
    mutation: {
      onSuccess: (result) => {
        setFeedback({ success: result.success, message: result.details ?? result.message });
        queryClient.invalidateQueries({ queryKey: getGetSettingsQueryKey() });
      },
      onError: (error) => setFeedback({ success: false, message: error.message }),
    },
  });

  const sendDailyReport = useSendDailyReport({
    mutation: {
      onSuccess: (result) => {
        setFeedback({ success: result.success, message: result.details ?? result.message });
        queryClient.invalidateQueries({ queryKey: getGetSettingsQueryKey() });
      },
      onError: (error) => setFeedback({ success: false, message: error.message }),
    },
  });

  useEffect(() => {
    if (!settingsQuery.data) return;
    setServerUrl(settingsQuery.data.kobo.serverUrl);
    setApiToken(settingsQuery.data.kobo.apiToken);
    setAutoSync(settingsQuery.data.kobo.autoSync);
    setSyncIntervalHours(String(settingsQuery.data.kobo.syncIntervalHours));

    setSmtpHost(settingsQuery.data.smtp.host || "smtp-relay.brevo.com");
    setSmtpPort(String(settingsQuery.data.smtp.port || 587));
    setSmtpUsername(settingsQuery.data.smtp.username);
    setSmtpPassword(settingsQuery.data.smtp.password);
    setSmtpFromName(settingsQuery.data.smtp.fromName || "Infosutra");
    setSmtpFromEmail(settingsQuery.data.smtp.fromEmail);
    setSmtpUseTls(settingsQuery.data.smtp.useTls);

    setDailyReportEnabled(settingsQuery.data.dailyReport.enabled);
    setDailyReportTime(settingsQuery.data.dailyReport.sendTime || "21:00");
    setDailyReportRecipients(settingsQuery.data.dailyReport.recipients.join("\n"));

    const extended = settingsQuery.data as typeof settingsQuery.data & {
      dqaDaily?: {
        enabled: boolean;
        sendTime: string;
        recipients: string[];
        lastSentOn?: string | null;
        studyId?: string | null;
      };
      general?: {
        aiEnabled?: boolean;
        aiApiKey?: string;
        aiModel?: string;
        aiBaseUrl?: string;
        organizationName?: string;
      };
    };
    if (extended.dqaDaily) {
      setDqaDailyEnabled(extended.dqaDaily.enabled);
      setDqaDailyTime(extended.dqaDaily.sendTime || "21:30");
      setDqaDailyRecipients((extended.dqaDaily.recipients || []).join("\n"));
      setDqaDailyStudyId(extended.dqaDaily.studyId || activeStudyId || "");
    }
    if (extended.general) {
      setAiEnabled(Boolean(extended.general.aiEnabled));
      setAiApiKey(extended.general.aiApiKey || "");
      setAiModel(extended.general.aiModel || "nvidia/nemotron-3-super-120b-a12b:free");
      setAiBaseUrl(extended.general.aiBaseUrl || "https://openrouter.ai/api/v1");
    }
  }, [settingsQuery.data, activeStudyId]);

  const saveKoboSettings = () => {
    setFeedback(null);
    updateSettings.mutate({
      data: {
        kobo: {
          serverUrl,
          apiToken,
          username: settingsQuery.data?.kobo.username ?? "",
          autoSync,
          syncIntervalHours: Number(syncIntervalHours),
          connected: settingsQuery.data?.kobo.connected ?? false,
          lastTestedAt: settingsQuery.data?.kobo.lastTestedAt ?? null,
        },
      },
    });
  };

  const saveSmtpSettings = () => {
    setFeedback(null);
    updateSettings.mutate({
      data: {
        smtp: {
          host: smtpHost,
          port: Number(smtpPort),
          username: smtpUsername,
          password: smtpPassword,
          fromName: smtpFromName,
          fromEmail: smtpFromEmail,
          useTls: smtpUseTls,
          connected: settingsQuery.data?.smtp.connected ?? false,
          lastTestedAt: settingsQuery.data?.smtp.lastTestedAt ?? null,
        },
        dailyReport: {
          enabled: dailyReportEnabled,
          sendTime: dailyReportTime,
          timezone: settingsQuery.data?.dailyReport.timezone ?? "Asia/Kolkata",
          recipients: parseRecipientInput(dailyReportRecipients),
          lastSentOn: settingsQuery.data?.dailyReport.lastSentOn ?? null,
        },
        dqaDaily: {
          enabled: dqaDailyEnabled,
          sendTime: dqaDailyTime,
          timezone: "Asia/Kolkata",
          recipients: parseRecipientInput(dqaDailyRecipients),
          lastSentOn:
            (settingsQuery.data as { dqaDaily?: { lastSentOn?: string | null } })?.dqaDaily
              ?.lastSentOn ?? null,
          studyId: dqaDailyStudyId || activeStudyId || null,
        },
      } as unknown as Parameters<typeof updateSettings.mutate>[0]["data"],
    });
  };

  const saveGeneralSettings = () => {
    setFeedback(null);
    const g = settingsQuery.data?.general;
    updateSettings.mutate({
      data: {
        general: {
          organizationName: g?.organizationName ?? "Sight Savers 2026",
          timezone: g?.timezone ?? "Asia/Kolkata",
          dateFormat: g?.dateFormat ?? "YYYY-MM-DD",
          language: g?.language ?? "en",
          aiEnabled,
          aiProvider: "openrouter",
          aiApiKey,
          reportLogoUrl: g?.reportLogoUrl ?? null,
          aiBaseUrl,
          aiModel,
          aiTemperature: 0.3,
          aiMaxTokens: 2048,
          aiTimeoutSeconds: 60,
        },
      } as unknown as Parameters<typeof updateSettings.mutate>[0]["data"],
    });
  };

  const saveCurrentTab = () => {
    if (activeTab === "smtp") {
      saveSmtpSettings();
      return;
    }
    if (activeTab === "general") {
      saveGeneralSettings();
      return;
    }
    saveKoboSettings();
  };

  return (
    <Layout>
      <Header 
        title="System Settings" 
        description="Configure integrations, preferences, and organization details"
        action={
          <Button
            size="sm"
            onClick={saveCurrentTab}
            disabled={updateSettings.isPending || settingsQuery.isLoading}
            className="bg-primary text-primary-foreground"
          >
            <Save className="w-4 h-4 mr-2" />
            {updateSettings.isPending
              ? "Saving…"
              : activeTab === "smtp"
                ? "Save Email Settings"
                : activeTab === "general"
                  ? "Save General Settings"
                  : "Save & Connect"}
          </Button>
        }
      />
      <div className="flex-1 overflow-auto p-4 md:p-6 bg-muted/30">
        
        <div className="max-w-4xl mx-auto">
          <Tabs
            value={activeTab}
            onValueChange={(value) => {
              setActiveTab(value);
              setFeedback(null);
            }}
          >
            <TabsList className="grid w-full grid-cols-3 mb-8">
              <TabsTrigger value="kobo" className="flex items-center gap-2">
                <Server className="w-4 h-4" /> KoboToolbox
              </TabsTrigger>
              <TabsTrigger value="smtp" className="flex items-center gap-2">
                <Mail className="w-4 h-4" /> SMTP Email
              </TabsTrigger>
              <TabsTrigger value="general" className="flex items-center gap-2">
                <Settings2 className="w-4 h-4" /> General
              </TabsTrigger>
            </TabsList>

            <TabsContent value="kobo">
              <Card>
                <CardHeader>
                  <CardTitle>KoboToolbox Integration</CardTitle>
                  <CardDescription>Connect to your KoboToolbox server to automatically sync form definitions and submission data.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="space-y-2">
                    <Label htmlFor="kobo-url">Server URL</Label>
                    <Input id="kobo-url" value={serverUrl} onChange={(event) => setServerUrl(event.target.value)} className="font-mono text-sm" />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="kobo-token">API Token</Label>
                    <Input id="kobo-token" type="password" value={apiToken} onChange={(event) => setApiToken(event.target.value)} placeholder="Paste your Kobo API token" className="font-mono" autoComplete="off" />
                    <p className="text-xs text-muted-foreground">The token is encrypted by the server and is never returned to this browser after saving.</p>
                  </div>
                  <div className="flex items-center justify-between p-4 border rounded-lg bg-muted/20">
                    <div className="space-y-0.5">
                      <Label className="text-base">Automatic Sync</Label>
                      <p className="text-sm text-muted-foreground">Pull new submissions automatically on a schedule.</p>
                    </div>
                    <Switch checked={autoSync} onCheckedChange={setAutoSync} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="sync-interval">Sync Interval (Hours)</Label>
                    <Select value={syncIntervalHours} onValueChange={setSyncIntervalHours}>
                      <SelectTrigger id="sync-interval">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="1">Every 1 hour</SelectItem>
                        <SelectItem value="6">Every 6 hours</SelectItem>
                        <SelectItem value="12">Every 12 hours</SelectItem>
                        <SelectItem value="24">Daily</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="pt-4 flex items-center gap-4">
                    <Button variant="outline" className="bg-card" disabled={!settingsQuery.data?.kobo.apiToken || testKoboConnection.isPending} onClick={() => testKoboConnection.mutate()}>
                      {testKoboConnection.isPending ? "Testing…" : "Test Saved Connection"}
                    </Button>
                    {settingsQuery.data?.kobo.connected && !feedback && (
                      <span className="text-sm text-green-600 dark:text-green-400 flex items-center font-medium">
                        <CheckCircle2 className="w-4 h-4 mr-2" /> Connected
                      </span>
                    )}
                  </div>
                  {feedback && activeTab === "kobo" && (
                    <div className={`flex items-start gap-2 rounded-md border p-3 text-sm ${feedback.success ? "border-green-200 bg-green-50 text-green-800 dark:border-green-900 dark:bg-green-950/30 dark:text-green-300" : "border-destructive/30 bg-destructive/5 text-destructive"}`}>
                      {feedback.success ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />}
                      {feedback.message}
                    </div>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="smtp">
              <Card>
                <CardHeader>
                  <CardTitle>Email Delivery (Brevo)</CardTitle>
                  <CardDescription>
                    Use Brevo SMTP for daily reports and alerts. Create an SMTP key in Brevo under
                    {" "}Settings → SMTP & API, and verify your sender email.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="rounded-md border bg-muted/20 p-4 text-sm text-muted-foreground space-y-1">
                    <p>Brevo defaults:</p>
                    <p className="font-mono text-xs">Host: smtp-relay.brevo.com</p>
                    <p className="font-mono text-xs">Port: 587</p>
                    <p className="font-mono text-xs">Username: your Brevo SMTP login email</p>
                    <p className="font-mono text-xs">Password: your Brevo SMTP key</p>
                  </div>
                  <div className="grid grid-cols-3 gap-4">
                    <div className="space-y-2 col-span-2">
                      <Label htmlFor="smtp-host">SMTP Host</Label>
                      <Input
                        id="smtp-host"
                        value={smtpHost}
                        onChange={(event) => setSmtpHost(event.target.value)}
                        placeholder="smtp-relay.brevo.com"
                        className="font-mono text-sm"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="smtp-port">Port</Label>
                      <Input
                        id="smtp-port"
                        value={smtpPort}
                        onChange={(event) => setSmtpPort(event.target.value)}
                        className="font-mono text-sm"
                      />
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="smtp-user">SMTP Login</Label>
                      <Input
                        id="smtp-user"
                        value={smtpUsername}
                        onChange={(event) => setSmtpUsername(event.target.value)}
                        placeholder="login email from Brevo"
                        autoComplete="off"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="smtp-pass">SMTP Key</Label>
                      <Input
                        id="smtp-pass"
                        type="password"
                        value={smtpPassword}
                        onChange={(event) => setSmtpPassword(event.target.value)}
                        placeholder="Paste your Brevo SMTP key"
                        className="font-mono"
                        autoComplete="off"
                      />
                      <p className="text-xs text-muted-foreground">Encrypted at rest. Never returned after saving.</p>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="from-name">From Name</Label>
                      <Input
                        id="from-name"
                        value={smtpFromName}
                        onChange={(event) => setSmtpFromName(event.target.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="from-email">From Email</Label>
                      <Input
                        id="from-email"
                        value={smtpFromEmail}
                        onChange={(event) => setSmtpFromEmail(event.target.value)}
                        placeholder="verified sender in Brevo"
                      />
                    </div>
                  </div>
                  <div className="flex items-center justify-between p-4 border rounded-lg bg-muted/20">
                    <div className="space-y-0.5">
                      <Label className="text-base">Use TLS</Label>
                      <p className="text-sm text-muted-foreground">Recommended for Brevo port 587.</p>
                    </div>
                    <Switch checked={smtpUseTls} onCheckedChange={setSmtpUseTls} />
                  </div>
                  <div className="pt-4 flex items-center gap-4">
                    <Button
                      variant="outline"
                      className="bg-card"
                      disabled={!settingsQuery.data?.smtp.password || testSmtpConnection.isPending}
                      onClick={() => testSmtpConnection.mutate()}
                    >
                      {testSmtpConnection.isPending ? "Sending…" : "Send Test Email"}
                    </Button>
                    {settingsQuery.data?.smtp.connected && !feedback && (
                      <span className="text-sm text-green-600 dark:text-green-400 flex items-center font-medium">
                        <CheckCircle2 className="w-4 h-4 mr-2" /> Connected
                      </span>
                    )}
                  </div>

                  <div className="pt-6 border-t space-y-6">
                    <div>
                      <h3 className="text-lg font-medium">Daily consolidated report</h3>
                      <p className="text-sm text-muted-foreground mt-1">
                        One email covering all projects: enumerator counts, invalid submissions with reasons, and totals for the day (Asia/Kolkata).
                      </p>
                    </div>
                    <div className="flex items-center justify-between p-4 border rounded-lg bg-muted/20">
                      <div className="space-y-0.5">
                        <Label className="text-base">Enable daily report</Label>
                        <p className="text-sm text-muted-foreground">
                          Sends automatically at the time below when SMTP and recipients are set.
                        </p>
                      </div>
                      <Switch checked={dailyReportEnabled} onCheckedChange={setDailyReportEnabled} />
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <Label htmlFor="daily-report-time">Send time (IST)</Label>
                        <Input
                          id="daily-report-time"
                          type="time"
                          value={dailyReportTime}
                          onChange={(event) => setDailyReportTime(event.target.value)}
                        />
                        <p className="text-xs text-muted-foreground">Default 21:00 Asia/Kolkata</p>
                      </div>
                      <div className="space-y-2">
                        <Label>Last sent</Label>
                        <p className="text-sm text-muted-foreground pt-2">
                          {settingsQuery.data?.dailyReport.lastSentOn ?? "Never"}
                        </p>
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="daily-report-recipients">Recipient emails</Label>
                      <Textarea
                        id="daily-report-recipients"
                        value={dailyReportRecipients}
                        onChange={(event) => setDailyReportRecipients(event.target.value)}
                        placeholder={"one@example.com\ntwo@example.com"}
                        rows={4}
                      />
                      <p className="text-xs text-muted-foreground">
                        One email per line, or separate with commas.
                      </p>
                    </div>
                    <Button
                      variant="outline"
                      className="bg-card"
                      disabled={
                        sendDailyReport.isPending ||
                        parseRecipientInput(dailyReportRecipients).length === 0 ||
                        !settingsQuery.data?.smtp.connected
                      }
                      onClick={() => {
                        setFeedback(null);
                        sendDailyReport.mutate();
                      }}
                    >
                      {sendDailyReport.isPending ? "Sending…" : "Send today’s report now"}
                    </Button>
                  </div>

                  <div className="pt-6 border-t space-y-6">
                    <div>
                      <h3 className="text-lg font-medium">DQA Daily report</h3>
                      <p className="text-sm text-muted-foreground mt-1">
                        Separate from the submission digest: study-scoped quality report with HTML
                        email and PDF attachment (targets, RED priority, enumerator watchlist).
                      </p>
                    </div>
                    <div className="flex items-center justify-between p-4 border rounded-lg bg-muted/20">
                      <div className="space-y-0.5">
                        <Label className="text-base">Enable DQA Daily email</Label>
                        <p className="text-sm text-muted-foreground">
                          Uses the same SMTP connection; schedule is independent.
                        </p>
                      </div>
                      <Switch checked={dqaDailyEnabled} onCheckedChange={setDqaDailyEnabled} />
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <Label htmlFor="dqa-daily-time">Send time (IST)</Label>
                        <Input
                          id="dqa-daily-time"
                          type="time"
                          value={dqaDailyTime}
                          onChange={(event) => setDqaDailyTime(event.target.value)}
                        />
                      </div>
                      <div className="space-y-2">
                        <Label>Last sent</Label>
                        <p className="text-sm text-muted-foreground pt-2">
                          {(
                            settingsQuery.data as {
                              dqaDaily?: { lastSentOn?: string | null };
                            }
                          )?.dqaDaily?.lastSentOn ?? "Never"}
                        </p>
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="dqa-daily-study">Study workspace</Label>
                      <select
                        id="dqa-daily-study"
                        className="h-9 w-full rounded-md border bg-background px-3 text-sm"
                        value={dqaDailyStudyId || activeStudyId || ""}
                        onChange={(e) => setDqaDailyStudyId(e.target.value)}
                      >
                        <option value="">Select a study…</option>
                        {studies.map((s) => (
                          <option key={s.id} value={s.id}>
                            {s.name}
                          </option>
                        ))}
                      </select>
                      <p className="text-xs text-muted-foreground">
                        DQA Daily is generated for this study’s forms and targets.
                      </p>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="dqa-daily-recipients">DQA Daily recipients</Label>
                      <Textarea
                        id="dqa-daily-recipients"
                        value={dqaDailyRecipients}
                        onChange={(event) => setDqaDailyRecipients(event.target.value)}
                        placeholder={"dqa@example.org"}
                        rows={3}
                      />
                    </div>
                    <Button
                      variant="outline"
                      className="bg-card"
                      disabled={
                        dqaDailySending ||
                        parseRecipientInput(dqaDailyRecipients).length === 0 ||
                        !settingsQuery.data?.smtp.connected
                      }
                      onClick={async () => {
                        setFeedback(null);
                        setDqaDailySending(true);
                        try {
                          const res = await fetch("/api/settings/send-dqa-daily-report", {
                            method: "POST",
                          });
                          const body = await res.json();
                          if (!res.ok) {
                            throw new Error(body.details || body.message || "Send failed");
                          }
                          setFeedback({
                            success: true,
                            message: body.details || body.message || "DQA Daily sent",
                          });
                          queryClient.invalidateQueries({ queryKey: getGetSettingsQueryKey() });
                        } catch (err) {
                          setFeedback({
                            success: false,
                            message: err instanceof Error ? err.message : "Send failed",
                          });
                        } finally {
                          setDqaDailySending(false);
                        }
                      }}
                    >
                      {dqaDailySending ? "Sending…" : "Send DQA Daily now"}
                    </Button>
                  </div>

                  {feedback && activeTab === "smtp" && (
                    <div className={`flex items-start gap-2 rounded-md border p-3 text-sm ${feedback.success ? "border-green-200 bg-green-50 text-green-800 dark:border-green-900 dark:bg-green-950/30 dark:text-green-300" : "border-destructive/30 bg-destructive/5 text-destructive"}`}>
                      {feedback.success ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />}
                      {feedback.message}
                    </div>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="general">
              <Card>
                <CardHeader>
                  <CardTitle>General Settings</CardTitle>
                  <CardDescription>Organization details and AI provider configuration.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="space-y-2">
                    <Label htmlFor="org-name">Organization Name</Label>
                    <Input id="org-name" defaultValue="Global Relief Foundation" />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="timezone">Timezone</Label>
                      <Select defaultValue="Africa/Nairobi">
                        <SelectTrigger id="timezone">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="Africa/Nairobi">Africa/Nairobi (EAT)</SelectItem>
                          <SelectItem value="UTC">UTC</SelectItem>
                          <SelectItem value="America/New_York">America/New_York (EST)</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="date-format">Date Format</Label>
                      <Select defaultValue="YYYY-MM-DD">
                        <SelectTrigger id="date-format">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="YYYY-MM-DD">YYYY-MM-DD</SelectItem>
                          <SelectItem value="DD/MM/YYYY">DD/MM/YYYY</SelectItem>
                          <SelectItem value="MM/DD/YYYY">MM/DD/YYYY</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                  
                  <div className="pt-6 border-t mt-6 space-y-4">
                    <h3 className="text-lg font-medium">AI Configuration (OpenRouter)</h3>
                    <p className="text-sm text-muted-foreground">
                      Powers DQA Daily headlines. Default model is the free Nemotron endpoint;
                      change model or base URL anytime.
                    </p>
                    <div className="flex items-center justify-between p-4 border rounded-lg bg-muted/20">
                      <div className="space-y-0.5">
                        <Label className="text-base">Enable AI narratives</Label>
                        <p className="text-sm text-muted-foreground">
                          When off, reports use a deterministic fallback summary.
                        </p>
                      </div>
                      <Switch checked={aiEnabled} onCheckedChange={setAiEnabled} />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="ai-base-url">Base URL</Label>
                      <Input
                        id="ai-base-url"
                        value={aiBaseUrl}
                        onChange={(e) => setAiBaseUrl(e.target.value)}
                        className="font-mono text-sm"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="ai-model">Model</Label>
                      <Input
                        id="ai-model"
                        value={aiModel}
                        onChange={(e) => setAiModel(e.target.value)}
                        className="font-mono text-sm"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="ai-key">OpenRouter API Key</Label>
                      <Input
                        id="ai-key"
                        type="password"
                        value={aiApiKey}
                        onChange={(e) => setAiApiKey(e.target.value)}
                        placeholder="sk-or-…"
                        className="font-mono text-sm"
                        autoComplete="off"
                      />
                    </div>
                    {feedback && activeTab === "general" && (
                      <div
                        className={`flex items-start gap-2 rounded-md border p-3 text-sm ${
                          feedback.success
                            ? "border-green-200 bg-green-50 text-green-800 dark:border-green-900 dark:bg-green-950/30 dark:text-green-300"
                            : "border-destructive/30 bg-destructive/5 text-destructive"
                        }`}
                      >
                        {feedback.success ? (
                          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                        ) : (
                          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                        )}
                        {feedback.message}
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

          </Tabs>
        </div>
      </div>
    </Layout>
  );
}
