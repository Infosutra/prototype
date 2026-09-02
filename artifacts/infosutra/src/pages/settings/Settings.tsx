import React, { useEffect, useState } from "react";
import {
  getGetSettingsQueryKey,
  useGetSettings,
  useGetUsageEvents,
  useGetUsageSummary,
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
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Save, CheckCircle2, Mail, Settings2, AlertCircle, ChevronDown, CircleHelp, Receipt } from "lucide-react";

const SARVAM_MODELS = [
  { value: "saaras:v3", label: "Saaras v3 (recommended)" },
  { value: "saaras:v4", label: "Saaras v4 (latest)" },
] as const;

const WHISPER_MODELS = [
  { value: "whisper-1", label: "whisper-1" },
  { value: "gpt-4o-transcribe", label: "gpt-4o-transcribe" },
  { value: "gpt-4o-mini-transcribe", label: "gpt-4o-mini-transcribe" },
] as const;

function defaultModelForProvider(provider: string): string {
  return provider === "whisper" ? "whisper-1" : "saaras:v3";
}

function modelsForProvider(
  provider: string,
  currentModel?: string,
): Array<{ value: string; label: string }> {
  const options: Array<{ value: string; label: string }> =
    provider === "whisper" ? [...WHISPER_MODELS] : [...SARVAM_MODELS];
  if (currentModel && !options.some((item) => item.value === currentModel)) {
    options.push({ value: currentModel, label: `${currentModel} (saved)` });
  }
  return options;
}

const smtpActionButtonClass =
  "bg-green-600 text-white border-green-700 hover:bg-green-700 dark:bg-green-700 dark:hover:bg-green-600 dark:border-green-600";

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
  const [aiCompileModel, setAiCompileModel] = useState("");
  const [aiBaseUrl, setAiBaseUrl] = useState("https://openrouter.ai/api/v1");

  const [transcriptionEnabled, setTranscriptionEnabled] = useState(false);
  const [transcriptionProvider, setTranscriptionProvider] = useState("sarvam");
  const [transcriptionApiKey, setTranscriptionApiKey] = useState("");
  const [transcriptionBaseUrl, setTranscriptionBaseUrl] = useState("https://api.sarvam.ai");
  const [transcriptionModel, setTranscriptionModel] = useState("saaras:v3");
  const [transcriptionCurrency, setTranscriptionCurrency] = useState("INR");
  const [transcriptionRatePerMinute, setTranscriptionRatePerMinute] = useState("0");

  const [feedback, setFeedback] = useState<{ success: boolean; message: string } | null>(null);

  const usageEventsQuery = useGetUsageEvents(undefined, {
    query: { enabled: activeTab === "usage" } as never,
  });
  const usageSummaryQuery = useGetUsageSummary(undefined, {
    query: { enabled: activeTab === "usage" } as never,
  });

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
        setAiCompileModel(settings.general.aiCompileModel || "");
        setAiBaseUrl(settings.general.aiBaseUrl || "https://openrouter.ai/api/v1");
        setTranscriptionApiKey(settings.general.transcriptionApiKey || "");
        setTranscriptionEnabled(Boolean(settings.general.transcriptionEnabled));
        setTranscriptionProvider(settings.general.transcriptionProvider || "sarvam");
        setTranscriptionBaseUrl(settings.general.transcriptionBaseUrl || "https://api.sarvam.ai");
        setTranscriptionModel(
          settings.general.transcriptionModel || defaultModelForProvider(
            settings.general.transcriptionProvider || "sarvam",
          ),
        );
        setTranscriptionCurrency(settings.general.transcriptionCurrency || "INR");
        setTranscriptionRatePerMinute(
          String(settings.general.transcriptionRatePerMinute ?? 0),
        );
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
    setAiCompileModel(settingsQuery.data.general.aiCompileModel || "");
    setAiBaseUrl(settingsQuery.data.general.aiBaseUrl || "https://openrouter.ai/api/v1");
    setTranscriptionEnabled(Boolean(settingsQuery.data.general.transcriptionEnabled));
    setTranscriptionProvider(settingsQuery.data.general.transcriptionProvider || "sarvam");
    setTranscriptionApiKey(settingsQuery.data.general.transcriptionApiKey || "");
    setTranscriptionBaseUrl(
      settingsQuery.data.general.transcriptionBaseUrl || "https://api.sarvam.ai",
    );
    setTranscriptionModel(
      settingsQuery.data.general.transcriptionModel ||
        defaultModelForProvider(settingsQuery.data.general.transcriptionProvider || "sarvam"),
    );
    setTranscriptionCurrency(settingsQuery.data.general.transcriptionCurrency || "INR");
    setTranscriptionRatePerMinute(
      String(settingsQuery.data.general.transcriptionRatePerMinute ?? 0),
    );
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
          aiCompileModel,
          aiTemperature: 0.3,
          aiMaxTokens: 2048,
          aiTimeoutSeconds: 60,
          transcriptionEnabled,
          transcriptionProvider,
          transcriptionApiKey,
          transcriptionBaseUrl,
          transcriptionModel,
          transcriptionCurrency,
          transcriptionRatePerMinute: Number(transcriptionRatePerMinute) || 0,
        },
      },
    });
  };

  const handleTranscriptionProviderChange = (provider: string) => {
    setTranscriptionProvider(provider);
    const options = modelsForProvider(provider);
    if (!options.some((item) => item.value === transcriptionModel)) {
      setTranscriptionModel(defaultModelForProvider(provider));
    }
    if (provider === "whisper") {
      setTranscriptionBaseUrl("https://api.openai.com/v1");
    } else {
      setTranscriptionBaseUrl("https://api.sarvam.ai");
    }
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
          <>
            {activeTab === "smtp" && (
              <Dialog>
                <DialogTrigger asChild>
                  <Button variant="outline" size="sm" aria-label="SMTP email help">
                    <CircleHelp className="mr-2 h-4 w-4" />
                    Help
                  </Button>
                </DialogTrigger>
                <DialogContent className="max-h-[85vh] overflow-y-auto">
                  <DialogHeader>
                    <DialogTitle>Email delivery help</DialogTitle>
                    <DialogDescription>
                      Brevo SMTP setup and daily consolidated report overview.
                    </DialogDescription>
                  </DialogHeader>
                  <div className="space-y-6 text-sm">
                    <div className="space-y-2">
                      <h3 className="font-semibold text-foreground">Email Delivery (Brevo)</h3>
                      <p className="text-muted-foreground">
                        Use Brevo SMTP for daily reports and alerts. Create an SMTP key in Brevo under
                        {" "}Settings → SMTP & API, and verify your sender email.
                      </p>
                    </div>
                    <Collapsible defaultOpen={false} className="rounded-md bg-muted/60 overflow-hidden">
                      <CollapsibleTrigger className="group flex w-full items-center justify-between px-3 py-2.5 text-sm text-muted-foreground hover:bg-muted/75 transition-colors">
                        <span>Brevo defaults</span>
                        <ChevronDown className="h-4 w-4 shrink-0 transition-transform group-data-[state=open]:rotate-180" />
                      </CollapsibleTrigger>
                      <CollapsibleContent className="space-y-1 px-3 pb-3 text-muted-foreground">
                        <p className="font-mono text-xs">Host: smtp-relay.brevo.com</p>
                        <p className="font-mono text-xs">Port: 587</p>
                        <p className="font-mono text-xs">Username: your Brevo SMTP login email</p>
                        <p className="font-mono text-xs">Password: your Brevo SMTP key</p>
                      </CollapsibleContent>
                    </Collapsible>
                    <div className="space-y-2 border-t pt-4">
                      <h3 className="font-semibold text-foreground">Daily consolidated report</h3>
                      <p className="text-muted-foreground">
                        One email covering all projects: enumerator counts, invalid submissions with
                        reasons, and totals for the day (Asia/Kolkata).
                      </p>
                    </div>
                  </div>
                </DialogContent>
              </Dialog>
            )}
            <Button
              size="sm"
              onClick={saveCurrentTab}
              disabled={updateSettings.isPending || settingsQuery.isLoading || activeTab === "usage"}
              className="bg-primary text-primary-foreground"
            >
              <Save className="w-4 h-4 mr-2" />
              {updateSettings.isPending
                ? "Saving…"
                : activeTab === "general"
                  ? "Save General Settings"
                  : "Save Email Settings"}
            </Button>
          </>
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
              <TabsTrigger value="smtp" className="flex items-center gap-2">
                <Mail className="w-4 h-4" /> SMTP Email
              </TabsTrigger>
              <TabsTrigger value="general" className="flex items-center gap-2">
                <Settings2 className="w-4 h-4" /> General
              </TabsTrigger>
              <TabsTrigger value="usage" className="flex items-center gap-2">
                <Receipt className="w-4 h-4" /> Usage
              </TabsTrigger>
            </TabsList>

            <TabsContent value="smtp">
              <Card>
                <CardContent className="pt-6 space-y-6">
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
                  <div className="setting-toggle-row">
                    <div className="space-y-0.5">
                      <Label className="text-base">Use TLS</Label>
                      <p className="text-sm text-muted-foreground">Recommended for Brevo port 587.</p>
                    </div>
                    <Switch checked={smtpUseTls} onCheckedChange={setSmtpUseTls} />
                  </div>
                  <div className="pt-4 flex items-center gap-4">
                    <Button
                      variant="outline"
                      className={smtpActionButtonClass}
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
                    <div className="setting-toggle-row">
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
                      className={smtpActionButtonClass}
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
                      Powers DQA Daily headlines and other narratives. DQA rule compilation can
                      use a separate model below.
                    </p>
                    <div className="setting-toggle-row">
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
                      <Label htmlFor="ai-compile-model">DQA compile model</Label>
                      <Input
                        id="ai-compile-model"
                        value={aiCompileModel}
                        onChange={(e) => setAiCompileModel(e.target.value)}
                        placeholder="Leave blank to use the model above"
                        className="font-mono text-sm"
                      />
                      <p className="text-xs text-muted-foreground">
                        Used only when compiling DQA rules from English (not runtime evaluation).
                      </p>
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

                    <div className="pt-6 border-t mt-6 space-y-4">
                      <h3 className="text-lg font-medium">Audio transcription</h3>
                      <p className="text-sm text-muted-foreground">
                        Configure Sarvam AI (Indian languages + diarization) or OpenAI Whisper.
                        Costs are recorded in the Usage tab.
                      </p>
                      <div className="setting-toggle-row">
                        <div className="space-y-0.5">
                          <Label className="text-base">Enable transcription</Label>
                          <p className="text-sm text-muted-foreground">
                            Required before recordings can be transcribed.
                          </p>
                        </div>
                        <Switch
                          checked={transcriptionEnabled}
                          onCheckedChange={setTranscriptionEnabled}
                        />
                      </div>
                      <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-2">
                          <Label htmlFor="transcription-provider">Provider</Label>
                          <Select
                            value={transcriptionProvider}
                            onValueChange={handleTranscriptionProviderChange}
                          >
                            <SelectTrigger id="transcription-provider">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="sarvam">Sarvam AI</SelectItem>
                              <SelectItem value="whisper">Whisper (OpenAI-compatible)</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                        <div className="space-y-2">
                          <Label htmlFor="transcription-model">Model</Label>
                          <Select
                            value={transcriptionModel}
                            onValueChange={setTranscriptionModel}
                          >
                            <SelectTrigger id="transcription-model">
                              <SelectValue placeholder="Select model" />
                            </SelectTrigger>
                            <SelectContent>
                              {modelsForProvider(transcriptionProvider, transcriptionModel).map((item) => (
                                <SelectItem key={item.value} value={item.value}>
                                  {item.label}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="transcription-base-url">Base URL</Label>
                        <Input
                          id="transcription-base-url"
                          value={transcriptionBaseUrl}
                          onChange={(e) => setTranscriptionBaseUrl(e.target.value)}
                          className="font-mono text-sm"
                        />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="transcription-api-key">API key</Label>
                        <Input
                          id="transcription-api-key"
                          type="password"
                          value={transcriptionApiKey}
                          onChange={(e) => setTranscriptionApiKey(e.target.value)}
                          className="font-mono text-sm"
                          autoComplete="off"
                        />
                        <p className="text-xs text-muted-foreground">
                          Encrypted at rest. Never returned after saving.
                        </p>
                      </div>
                      <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-2">
                          <Label htmlFor="transcription-currency">Cost currency</Label>
                          <Input
                            id="transcription-currency"
                            value={transcriptionCurrency}
                            onChange={(e) => setTranscriptionCurrency(e.target.value)}
                          />
                        </div>
                        <div className="space-y-2">
                          <Label htmlFor="transcription-rate">Rate per minute</Label>
                          <Input
                            id="transcription-rate"
                            type="number"
                            min="0"
                            step="0.01"
                            value={transcriptionRatePerMinute}
                            onChange={(e) => setTranscriptionRatePerMinute(e.target.value)}
                          />
                          <p className="text-xs text-muted-foreground">
                            Used when the provider does not return a bill.
                          </p>
                        </div>
                      </div>
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

            <TabsContent value="usage">
              <Card>
                <CardHeader>
                  <CardTitle>Usage & costs</CardTitle>
                  <CardDescription>
                    Transcription and other AI service expenses across all studies.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  {usageSummaryQuery.data && (
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                      <div className="rounded-md border bg-card p-4">
                        <p className="text-xs text-muted-foreground uppercase tracking-wide">Total</p>
                        <p className="text-2xl font-semibold mt-1">
                          {usageSummaryQuery.data.currency}{" "}
                          {usageSummaryQuery.data.totalAmount.toFixed(2)}
                        </p>
                      </div>
                      {usageSummaryQuery.data.items.map((item) => (
                        <div key={item.category} className="rounded-md border bg-card p-4">
                          <p className="text-xs text-muted-foreground uppercase tracking-wide">
                            {item.category}
                          </p>
                          <p className="text-xl font-semibold mt-1">
                            {item.currency} {item.totalAmount.toFixed(2)}
                          </p>
                          <p className="text-xs text-muted-foreground mt-1">
                            {item.eventCount} event{item.eventCount === 1 ? "" : "s"}
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                  {usageEventsQuery.isLoading ? (
                    <p className="text-sm text-muted-foreground">Loading usage events…</p>
                  ) : (usageEventsQuery.data ?? []).length === 0 ? (
                    <p className="text-sm text-muted-foreground">No usage recorded yet.</p>
                  ) : (
                    <div className="overflow-x-auto rounded-md border">
                      <table className="w-full min-w-[640px] text-sm">
                        <thead className="bg-muted/50 text-left">
                          <tr>
                            <th className="p-3 font-medium">When</th>
                            <th className="p-3 font-medium">Category</th>
                            <th className="p-3 font-medium">Provider</th>
                            <th className="p-3 font-medium">Quantity</th>
                            <th className="p-3 font-medium text-right">Amount</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(usageEventsQuery.data ?? []).map((event) => (
                            <tr key={event.id} className="border-t">
                              <td className="p-3 text-muted-foreground">
                                {new Date(event.occurredAt).toLocaleString()}
                              </td>
                              <td className="p-3">{event.category}</td>
                              <td className="p-3">{event.provider}</td>
                              <td className="p-3 font-mono text-xs">
                                {event.quantity.toFixed(1)} {event.unit}
                              </td>
                              <td className="p-3 text-right font-medium">
                                {event.currency} {event.amount.toFixed(2)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </Layout>
  );
}
