/**
 * 错误处理模块
 * 
 * 提供API错误分类、错误提示和错误日志记录功能
 */

// ==================== 错误类型常量 ====================

// 网络错误类型
const NETWORK_ERROR_TYPES = {
    TIMEOUT: 'TIMEOUT',
    CONNECTION_REFUSED: 'CONNECTION_REFUSED',
    NETWORK_UNREACHABLE: 'NETWORK_UNREACHABLE',
    DNS_FAILED: 'DNS_FAILED'
};

// HTTP错误状态码
const HTTP_ERROR_CODES = {
    BAD_REQUEST: 400,
    UNAUTHORIZED: 401,
    FORBIDDEN: 403,
    NOT_FOUND: 404,
    INTERNAL_SERVER_ERROR: 500,
    BAD_GATEWAY: 502,
    SERVICE_UNAVAILABLE: 503,
    GATEWAY_TIMEOUT: 504
};

// 业务错误类型
const BUSINESS_ERROR_TYPES = {
    TASK_NOT_FOUND: 'TASK_NOT_FOUND',
    TASK_COMPLETED: 'TASK_COMPLETED',
    TASK_CANCELLED: 'TASK_CANCELLED',
    VALIDATION_FAILED: 'VALIDATION_FAILED',
    DATA_FORMAT_ERROR: 'DATA_FORMAT_ERROR'
};

// 应用错误类型
const APPLICATION_ERROR_TYPES = {
    JSON_PARSE_ERROR: 'JSON_PARSE_ERROR',
    RESPONSE_FORMAT_ERROR: 'RESPONSE_FORMAT_ERROR',
    DATA_TYPE_ERROR: 'DATA_TYPE_ERROR',
    UNKNOWN_ERROR: 'UNKNOWN_ERROR'
};

// ==================== 错误类定义 ====================

/**
 * API错误基类
 */
class APIError extends Error {
    constructor(code, message, details = null) {
        super(message);
        this.code = code;
        this.message = message;
        this.details = details;
        this.isRetryable = false;
        this.timestamp = new Date().toISOString();
    }

    /**
     * 转换为JSON格式
     */
    toJSON() {
        return {
            code: this.code,
            message: this.message,
            details: this.details,
            isRetryable: this.isRetryable,
            timestamp: this.timestamp
        };
    }
}

/**
 * 网络错误
 */
class NetworkError extends APIError {
    constructor(type, message, details = null) {
        super(`NETWORK_${type}`, message, details);
        this.type = type;
        this.isRetryable = true;
    }
}

/**
 * HTTP错误
 */
class HTTPError extends APIError {
    constructor(statusCode, message, details = null) {
        super(`HTTP_${statusCode}`, message, details);
        this.statusCode = statusCode;
        // 502、503、504 可重试
        this.isRetryable = [502, 503, 504].includes(statusCode);
    }
}

/**
 * 业务错误
 */
class BusinessError extends APIError {
    constructor(type, message, details = null) {
        super(`BUSINESS_${type}`, message, details);
        this.type = type;
        this.isRetryable = false;
    }
}

/**
 * 应用错误
 */
class ApplicationError extends APIError {
    constructor(type, message, details = null) {
        super(`APPLICATION_${type}`, message, details);
        this.type = type;
        this.isRetryable = false;
    }
}

// ==================== 错误分类函数 ====================

/**
 * 判断错误是否为网络错误
 */
function isNetworkError(error) {
    return error instanceof NetworkError;
}

/**
 * 判断错误是否为HTTP错误
 */
function isHTTPError(error) {
    return error instanceof HTTPError;
}

/**
 * 判断错误是否为业务错误
 */
function isBusinessError(error) {
    return error instanceof BusinessError;
}

/**
 * 判断错误是否为应用错误
 */
function isApplicationError(error) {
    return error instanceof ApplicationError;
}

/**
 * 判断错误是否可重试
 */
function isRetryable(error) {
    return error instanceof APIError && error.isRetryable;
}

// ==================== 错误提示函数 ====================

/**
 * 获取用户友好的错误提示信息
 */
function getErrorMessage(error) {
    // 网络错误提示
    if (isNetworkError(error)) {
        switch (error.type) {
            case NETWORK_ERROR_TYPES.TIMEOUT:
                return '网络连接超时，请检查网络连接';
            case NETWORK_ERROR_TYPES.CONNECTION_REFUSED:
                return '连接被拒绝，请检查服务器状态';
            case NETWORK_ERROR_TYPES.NETWORK_UNREACHABLE:
                return '网络不可达，请检查网络连接';
            case NETWORK_ERROR_TYPES.DNS_FAILED:
                return 'DNS解析失败，请检查网络连接';
            default:
                return '网络错误，请稍后重试';
        }
    }

    // HTTP错误提示
    if (isHTTPError(error)) {
        switch (error.statusCode) {
            case HTTP_ERROR_CODES.BAD_REQUEST:
                return '请求参数错误，请检查输入';
            case HTTP_ERROR_CODES.UNAUTHORIZED:
                return '未授权，请重新登录';
            case HTTP_ERROR_CODES.FORBIDDEN:
                return '禁止访问，权限不足';
            case HTTP_ERROR_CODES.NOT_FOUND:
                return '资源不存在';
            case HTTP_ERROR_CODES.INTERNAL_SERVER_ERROR:
                return '服务器内部错误，请稍后重试';
            case HTTP_ERROR_CODES.BAD_GATEWAY:
                return '网关错误，请稍后重试';
            case HTTP_ERROR_CODES.SERVICE_UNAVAILABLE:
                return '服务暂时不可用，请稍后重试';
            case HTTP_ERROR_CODES.GATEWAY_TIMEOUT:
                return '请求超时，请稍后重试';
            default:
                return `HTTP错误 ${error.statusCode}，请稍后重试`;
        }
    }

    // 业务错误提示
    if (isBusinessError(error)) {
        switch (error.type) {
            case BUSINESS_ERROR_TYPES.TASK_NOT_FOUND:
                return '任务不存在';
            case BUSINESS_ERROR_TYPES.TASK_COMPLETED:
                return '任务已完成';
            case BUSINESS_ERROR_TYPES.TASK_CANCELLED:
                return '任务已取消';
            case BUSINESS_ERROR_TYPES.VALIDATION_FAILED:
                return `参数验证失败：${error.details || ''}`;
            case BUSINESS_ERROR_TYPES.DATA_FORMAT_ERROR:
                return '数据格式错误';
            default:
                return error.message || '业务错误';
        }
    }

    // 应用错误提示
    if (isApplicationError(error)) {
        switch (error.type) {
            case APPLICATION_ERROR_TYPES.JSON_PARSE_ERROR:
                return '数据解析失败，请稍后重试';
            case APPLICATION_ERROR_TYPES.RESPONSE_FORMAT_ERROR:
                return '响应格式错误，请稍后重试';
            case APPLICATION_ERROR_TYPES.DATA_TYPE_ERROR:
                return '数据类型错误，请稍后重试';
            case APPLICATION_ERROR_TYPES.UNKNOWN_ERROR:
                return '发生未知错误，请稍后重试';
            default:
                return '应用错误，请稍后重试';
        }
    }

    // 其他错误
    return error.message || '发生错误，请稍后重试';
}

// ==================== 错误日志函数 ====================

/**
 * 错误日志记录器
 */
class ErrorLogger {
    constructor() {
        this.logs = [];
        this.maxLogs = 1000;
    }

    /**
     * 记录错误
     */
    log(error, context = {}) {
        // 创建日志条目
        const logEntry = {
            timestamp: new Date().toISOString(),
            error: error instanceof APIError ? error.toJSON() : {
                code: 'UNKNOWN',
                message: error.message || String(error)
            },
            context: context,
            userAgent: navigator.userAgent
        };

        // 添加到日志列表
        this.logs.push(logEntry);

        // 限制日志数量
        if (this.logs.length > this.maxLogs) {
            this.logs.shift();
        }

        // 输出到控制台
        console.error(`[${logEntry.timestamp}] ${logEntry.error.code}: ${logEntry.error.message}`, logEntry);

        return logEntry;
    }

    /**
     * 获取所有日志
     */
    getLogs() {
        return [...this.logs];
    }

    /**
     * 获取最近的N条日志
     */
    getRecentLogs(count = 10) {
        return this.logs.slice(-count);
    }

    /**
     * 清空日志
     */
    clear() {
        this.logs = [];
    }

    /**
     * 导出日志为JSON
     */
    exportJSON() {
        return JSON.stringify(this.logs, null, 2);
    }
}

// 创建全局错误日志记录器
const errorLogger = new ErrorLogger();

// ==================== 错误处理装饰器 ====================

/**
 * 错误处理装饰器
 * 
 * 用法：
 * @withErrorHandling
 * async function myAPICall() { ... }
 */
function withErrorHandling(target, propertyKey, descriptor) {
    const originalMethod = descriptor.value;

    descriptor.value = async function(...args) {
        try {
            return await originalMethod.apply(this, args);
        } catch (error) {
            // 记录错误
            errorLogger.log(error, {
                method: propertyKey,
                args: args
            });

            // 返回错误响应
            return {
                success: false,
                error: {
                    code: error.code || 'UNKNOWN_ERROR',
                    message: getErrorMessage(error),
                    details: error.details
                }
            };
        }
    };

    return descriptor;
}

// ==================== 错误处理工具函数 ====================

/**
 * 处理API响应错误
 */
function handleResponseError(response) {
    // 检查HTTP状态码
    if (!response.ok) {
        throw new HTTPError(
            response.status,
            `HTTP ${response.status}`,
            { url: response.url }
        );
    }

    return response;
}

/**
 * 处理JSON解析错误
 */
function handleJSONParseError(text) {
    try {
        return JSON.parse(text);
    } catch (error) {
        throw new ApplicationError(
            APPLICATION_ERROR_TYPES.JSON_PARSE_ERROR,
            '数据解析失败',
            { originalError: error.message }
        );
    }
}

/**
 * 验证API响应格式
 */
function validateResponseFormat(data) {
    // 检查必需字段
    if (typeof data !== 'object' || data === null) {
        throw new ApplicationError(
            APPLICATION_ERROR_TYPES.RESPONSE_FORMAT_ERROR,
            '响应格式错误',
            { expected: 'object', received: typeof data }
        );
    }

    // 检查success字段
    if (!('success' in data)) {
        throw new ApplicationError(
            APPLICATION_ERROR_TYPES.RESPONSE_FORMAT_ERROR,
            '响应缺少success字段'
        );
    }

    return data;
}

/**
 * 处理业务错误响应
 */
function handleBusinessError(response) {
    // 如果success为false，说明是业务错误
    if (!response.success) {
        throw new BusinessError(
            response.error?.code || 'UNKNOWN',
            response.error?.message || '业务错误',
            response.error?.details
        );
    }

    return response;
}

// ==================== 导出 ====================

// 导出错误类
window.APIError = APIError;
window.NetworkError = NetworkError;
window.HTTPError = HTTPError;
window.BusinessError = BusinessError;
window.ApplicationError = ApplicationError;

// 导出错误类型常量
window.NETWORK_ERROR_TYPES = NETWORK_ERROR_TYPES;
window.HTTP_ERROR_CODES = HTTP_ERROR_CODES;
window.BUSINESS_ERROR_TYPES = BUSINESS_ERROR_TYPES;
window.APPLICATION_ERROR_TYPES = APPLICATION_ERROR_TYPES;

// 导出错误分类函数
window.isNetworkError = isNetworkError;
window.isHTTPError = isHTTPError;
window.isBusinessError = isBusinessError;
window.isApplicationError = isApplicationError;
window.isRetryable = isRetryable;

// 导出错误提示函数
window.getErrorMessage = getErrorMessage;

// 导出错误日志记录器
window.ErrorLogger = ErrorLogger;
window.errorLogger = errorLogger;

// 导出错误处理工具函数
window.handleResponseError = handleResponseError;
window.handleJSONParseError = handleJSONParseError;
window.validateResponseFormat = validateResponseFormat;
window.handleBusinessError = handleBusinessError;
