import React, { useEffect, useState } from "react";
import {
  getGetSettingsQueryKey,
  useGetSettings,
  useSendDailyReport,
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
import { Save, CheckCircle2, Mail, Settings2, AlertCircle } from "lucide-react";

function parseRecipientInput(value: string): string[] {
  return [...new Set(value.split(/[,;\n]+/).map((item) => item.trim()).filter(Boolean))];
}

export default function Settings() {
  const queryClient = useQueryClient();
  const settingsQuery = useGetSettings();
  const [activeTab, setActiveTab] = useState("smtp");

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

  const [aiEnabled, setAiEnabled] = useState(false);
  const [aiApiKey, setAiApiKey] = useState("");
  const [aiModel, setAiModel] = useState("nvidia/nemotron-3-super-120b-a12b:free");
  const [aiBaseUrl, setAiBaseUrl] = useState("https://openrouter.ai/api/v1");

  const [feedback, setFeedback] = useState<{ success: boolean; message: string } | null>(null);

  const updateSettings = useUpdateSettings({
    mutation: {
      onSuccess: (settings) => {
        setSmtpPassword(settings.smtp.password);
        setDailyReportEnabled(settings.dailyReport.enabled);
        setDailyReportTime(settings.dailyReport.sendTime || "21:00");
        setDailyReportRecipients(settings.dailyReport.recipients.join("\n"));
        setAiEnabled(Boolean(settings.general.aiEnabled));
        setAiApiKey(settings.general.aiApiKey || "");
        setAiModel(settings.general.aiModel || "nvidia/nemotron-3-super-120b-a12b:free");
        setAiBaseUrl(settings.general.aiBaseUrl || "https://openrouter.ai/api/v1");
        setFeedback({
          success: true,
          message:
            activeTab === "general"
              ? "General / AI settings saved."
              : "Email settings saved.",
        });
        queryClient.invalidateQueries({ queryKey: getGetSettingsQueryKey() });
      },
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

    setAiEnabled(Boolean(settingsQuery.data.general.aiEnabled));
    setAiApiKey(settingsQuery.data.general.aiApiKey || "");
    setAiModel(settingsQuery.data.general.aiModel || "nvidia/nemotron-3-super-120b-a12b:free");
    setAiBaseUrl(settingsQuery.data.general.aiBaseUrl || "https://openrouter.ai/api/v1");
  }, [settingsQuery.data]);

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
      },
    });
  };

  const saveGeneralSettings = () => {
    setFeedback(null);
    const g = settingsQuery.data?.general;
    updateSettings.mutate({
      data: {
        general: {
          organizationName: g?.organizationName ?? "Infosutra",
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
      },
    });
  };

  const saveCurrentTab = () => {
    if (activeTab === "general") {
      saveGeneralSettings();
      return;
    }
    saveSmtpSettings();
  };

  return (
    <Layout>
      <Header
        title="System Settings"
        description="Configure email delivery and organization details. Kobo credentials live on each study."
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
              : activeTab === "general"
                ? "Save General Settings"
                : "Save Email Settings"}
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
            <TabsList className="grid w-full grid-cols-2 mb-8">
              <TabsTrigger value="smtp" className="flex items-center gap-2">
                <Mail className="w-4 h-4" /> SMTP Email
              </TabsTrigger>
              <TabsTrigger value="general" className="flex items-center gap-2">
                <Settings2 className="w-4 h-4" /> General
              </TabsTrigger>
            </TabsList>

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
                    <Input id="org-name" defaultValue={settingsQuery.data?.general.organizationName ?? "Infosutra"} />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="timezone">Timezone</Label>
                      <Select defaultValue="Asia/Kolkata">
                        <SelectTrigger id="timezone">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="Asia/Kolkata">Asia/Kolkata (IST)</SelectItem>
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
